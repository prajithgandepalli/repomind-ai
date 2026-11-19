import React, {useEffect, useState} from 'react'

import './style.css'

const services = [
  ['backend', 'FastAPI', 'Python application server', '‹/›'],
  ['mongodb', 'MongoDB', 'Document database', '▤'],
  ['qdrant', 'Qdrant', 'Vector database', '⬡']
]

export default function Setup() {
  const [checks,setChecks] = useState({})
  const [busy,setBusy] = useState(true)
  const [checked,setChecked] = useState(null)
  async function check() {
    setBusy(true)
    const start = performance.now()
    try {
      const response = await fetch('/api/health',{cache:'no-store',signal:AbortSignal.timeout(7000)})
      const data = await response.json()
      if (typeof data.services?.mongodb?.online !== 'boolean' || typeof data.services?.qdrant?.online !== 'boolean') throw Error()
      setChecks({...data.services,backend:{online:true,ms:Math.round(performance.now()-start)}})
    } catch {
      setChecks({backend:{online:false}})
    } finally {
      setBusy(false)
      setChecked(new Date())
    }
  }
  useEffect(()=>{check()},[])
  const count = Object.values(checks).filter(item=>item.online).length
  return <div><header className="flex items-center justify-between"><strong className="brand"><i>R</i> RepoMind <em>AI</em></strong><span className="environment">● &nbsp; Local workspace</span></header>
    <main><p className="eyebrow">WORKSPACE / PHASE 01</p><h1>Environment setup</h1><p className="intro">Check the services that power your local RepoMind workspace.</p>
    <section className="summary flex flex-wrap items-center justify-between gap-4" aria-live="polite"><div><p className="eyebrow">SYSTEM STATUS</p><h2>{busy?'Checking connections…':count===3?'Workspace ready':'Connections need attention'}</h2><p>{busy?'Contacting your local services.':count+' of 3 services connected'}</p></div><button onClick={check} disabled={busy}>↻ &nbsp;{busy?'Checking…':'Run checks'}</button></section>
    <div className="sectionhead"><h2>Service connections</h2><span>03 SERVICES</span></div><section className="rows">{services.map(([key,title,desc,icon])=>{
      const result=checks[key]
      const status=busy?'Checking':result?.online?'Connected':result?'Offline':'Unknown'
      return <article key={key} className="flex items-center gap-4"><div aria-hidden="true" className={'icon '+key}>{icon}</div><div className="grow"><h3>{title}</h3><p>{desc}</p></div><small>{!busy && result?.online ? result.ms+' ms':''}</small><b className={'badge '+status}>{status}</b></article>
    })}</section><footer><a href="/dashboard">Workspace dashboard</a> · {checked?'Last checked '+checked.toLocaleTimeString():'First check in progress'}</footer></main></div>
}

