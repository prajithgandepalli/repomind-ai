import React,{useEffect,useState} from 'react'
import axios from 'axios'
import Markdown from 'react-markdown'
import highlight from 'rehype-highlight'
import './chat.css'

const client=axios.create({baseURL:'/api',timeout:180000,headers:{'X-RepoMind-CSRF':'1'}})
const questions=['Where does the application start?','How does data move through this project?']

export default function Chat(){
  const repo=new URLSearchParams(location.search).get('repo')
  const [info,setInfo]=useState(null),[threads,setThreads]=useState([]),[selected,select]=useState('')
  const [turns,setTurns]=useState([]),[question,setQuestion]=useState(''),[busy,setBusy]=useState(true),[error,setError]=useState('')
  function fail(e){
    if(e.response?.status===401)location.replace('/login')
    setError(e.response?.data?.detail||'Could not reach RepoMind. Please try again.')
  }
  async function open(id){
    setBusy(true);setError('');select(id);setTurns([]);setQuestion('')
    try{if(id)setTurns((await client.get('/conversations/'+id+'/messages')).data)}
    catch(e){fail(e)}finally{setBusy(false)}
  }
  async function list(){
    const {data}=await client.get('/repositories/'+repo+'/conversations')
    setThreads(data)
    return data
  }
  useEffect(()=>{
    async function load(){
      try{setInfo((await client.get('/repositories/'+repo)).data);const items=await list();await open(items[0]?.id||'')}
      catch(e){fail(e);setBusy(false)}
    }
    load()
  },[repo])
  async function send(e){
    e.preventDefault()
    if(busy||!question.trim())return
    setBusy(true);setError('')
    try{
      let id=selected
      if(!id){id=(await client.post('/repositories/'+repo+'/conversations')).data.id;select(id);await list()}
      const {data}=await client.post('/conversations/'+id+'/messages',{question:question.trim()})
      setTurns(v=>[...v,data]);setQuestion('');await list()
    }catch(e){fail(e)}finally{setBusy(false)}
  }
  async function remove(){
    if(!window.confirm('Delete this conversation and its messages?'))return
    setBusy(true)
    try{await client.delete('/conversations/'+selected);const items=await list();await open(items[0]?.id||'')}
    catch(e){fail(e)}finally{setBusy(false)}
  }
  return <div className="chat"><a href="/dashboard">← Workspace</a><h1>{info?.name||'Repository chat'}</h1>
    {info && <p className="revision">{info.owner}/{info.name} · {info.commit_sha?.slice(0,12)}</p>}
    <div className="chat-layout"><aside><h2>Conversations</h2><button disabled={busy} onClick={()=>open('')}>New conversation</button>
      {threads.map(t=><button className="thread" aria-current={selected===t.id?'page':undefined} disabled={busy} key={t.id} onClick={()=>open(t.id)}>{t.title}</button>)}</aside>
    <section aria-label="Conversation"><div className="chatbar"><h2>Source questions</h2>{selected && <button disabled={busy} onClick={remove}>Delete chat</button>}</div>
      {turns.map(t=><article key={t.id}><h3>You</h3><p>{t.question}</p><h3>RepoMind</h3>{t.answer.map((p,i)=><div key={i}>
        <Markdown skipHtml rehypePlugins={[highlight]} components={{a:({children})=><>{children}</>,img:()=>null}}>{p.text}</Markdown>
        <div className="citations">{p.citations.map(c=><a key={c.url} target="_blank" rel="noopener noreferrer" href={c.url}>{c.path} · L{c.start}–{c.end}</a>)}</div></div>)}</article>)}
      {!turns.length && !busy && <div className="suggest"><p>Ask about the code in this commit.</p>{questions.map(q=><button key={q} onClick={()=>setQuestion(q)}>{q}</button>)}</div>}
      {error && <p role="alert">{error}</p>}{busy && <p role="status">Working…</p>}
      <form onSubmit={send}><label htmlFor="question">Your question</label><textarea id="question" value={question} maxLength={2000} onChange={e=>setQuestion(e.target.value)} disabled={busy||info?.index_state!=='completed'}/>
      <button disabled={busy||!question.trim()||info?.index_state!=='completed'}>Ask RepoMind</button></form>
    </section></div></div>
}

