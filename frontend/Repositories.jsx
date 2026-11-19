import React, {useEffect, useState} from 'react'
import axios from 'axios'

const repos = axios.create({baseURL:'/api/repositories',timeout:12000,headers:{'X-RepoMind-CSRF':'1'}})
const labels = {queued:'Queued',retrieving:'Retrieving source',retrieved:'Source retrieved',failed:'Retrieval failed'}

function message(e) {
  if (e.response?.status===401) location.replace('/login')
  return typeof e.response?.data?.detail==='string' ? e.response.data.detail : 'Connection unavailable. Please try again.'
}

export default function Repositories() {
  const [items,setItems] = useState(null)
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  const [url,setUrl] = useState('')
  const [revision,refresh] = useState(0)
  useEffect(()=>{
    let mounted=true, timer
    async function poll() {
      try {
        const {data}=await repos.get('')
        if (mounted) {setItems(data);setError('');if(data.some(r=>['queued','retrieving'].includes(r.status)||['pending','processing'].includes(r.index_state))) timer=setTimeout(poll,2500)}
      } catch(e) {if(mounted) setError(message(e))}

    }
    poll()
    return ()=>{mounted=false;clearTimeout(timer)}
  },[revision])
  const [actionError,setActionError]=useState('')
  async function act(operation) {
    setBusy(true);setActionError('')
    try {await operation();refresh(v=>v+1)}
    catch(e){setActionError(message(e))}
    finally {setBusy(false)}
  }
  return <section className="repos"><h2>Repositories</h2>
    <p>Retrieve a public repository’s source at a fixed commit. Indexing starts after the source is retrieved.</p>
    <form onSubmit={e=>{e.preventDefault();act(async()=>{await repos.post('',{url});setUrl('')})}}>
      <label htmlFor="github-url">Public GitHub URL</label><div className="flex flex-wrap gap-2">
      <input id="github-url" type="url" placeholder="https://github.com/owner/repository" required value={url} onChange={e=>setUrl(e.target.value)}/>
      <button disabled={busy}>Retrieve source</button></div></form>
    {(error||actionError) && <p role="alert">{actionError||error}</p>}
    {items===null?<p>Loading repositories…</p>:!items.length?<p>No repositories added yet.</p>:items.map(item=><article key={item.id}>
      <h3>{item.owner}/{item.name}</h3><p>{item.description}</p>
      <p>{labels[item.status]} · {item.file_count} files{item.language && ' · '+item.language}</p>
      {item.commit_sha && <small>Commit <code>{item.commit_sha}</code></small>}
      {item.status==='retrieved' && <div className="index-info"><strong>AI index · {item.index_state || 'Not started'}</strong>
        {item.chunk_count>0 && <span> · {item.chunk_count} chunks</span>}
        {item.index_error && <p role="alert">{item.index_error}</p>}
        {(!item.index_state || item.index_state==='failed') && <button disabled={busy||item.deleting} onClick={()=>act(()=>repos.post('/'+item.id+'/index'))}>{item.index_state?'Retry indexing':'Index source'}</button>}
        {item.index_state==='completed' && !item.deleting && <a href={'/chat?repo='+item.id}>Open chat</a>}</div>}
      {item.error && <p role="alert">{item.error}</p>}
      <button disabled={busy} onClick={()=>{if(window.confirm('Delete this repository, its source, vectors and all conversations?')) act(()=>repos.delete('/'+item.id))}}>Delete</button>
    </article>)}</section>
}

