import React, {useEffect, useState} from 'react'
import {createRoot} from 'react-dom/client'
import {api} from './api'
import Setup from './Setup'
import Repositories from './Repositories'
const Chat = React.lazy(()=>import('./Chat'))
import './style.css'
import './account.css'

function AccountForm({register}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault()
    if (busy) return
    const data = Object.fromEntries(new FormData(event.currentTarget))
    if (new TextEncoder().encode(data.password).length > 72) {
      setError('Password exceeds 72 UTF-8 bytes. Some characters use more than one byte.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.post(register ? '/register' : '/login', data)
      location.replace(register ? '/login?registered=1' : '/dashboard')
    } catch (failure) {
      const messages = {401:'Email or password is incorrect.',409:'An account already uses this email.',422:'Check the email and password requirements.'}
      setError(messages[failure.response?.status] || 'Unable to complete the request. Please try again.')
      setBusy(false)
    }
  }
  return <section className="account"><p className="eyebrow">WORKSPACE ACCESS</p><h1>{register?'Create account':'Sign in'}</h1>
    {!register && location.search==='?registered=1' && <p role="status">Account created. Sign in to your workspace.</p>}
    <form className="grid gap-4" onSubmit={submit}>
      {register && <label>Username<input name="username" required pattern="[A-Za-z0-9_\-]{3,32}" autoComplete="username"/><small>3–32 letters, numbers, underscores or hyphens.</small></label>}
      <label>Email address<input type="email" autoComplete="email" name="email" required/></label>
      <label>Password<input name="password" type="password" required minLength={register?12:1} autoComplete={register?'new-password':'current-password'}/>{register && <small>At least 12 characters and at most 72 UTF-8 bytes.</small>}</label>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy}>{busy?'Please wait…':register?'Create account':'Sign in'}</button>
    </form><a href={register?'/login':'/register'}>{register?'Already registered? Sign in':'Create an account'}</a></section>
}

function Workspace() {
  const [user,setUser] = useState(null)
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  const path = location.pathname
  const form = path==='/register' || path==='/login'
  useEffect(()=>{
    async function restore() {
      try {
        const {data} = await api.get('/me')
        if (form) location.replace('/dashboard')
        else setUser(data)
      } catch (failure) {
        if (failure.response?.status===401) {
          setUser(null)
          if (!form) location.replace('/login')
        } else setError('Session check unavailable. Reload to try again.')
      }
    }
    restore()
    const revisit = event=>{if(event.persisted) location.reload()}
    window.addEventListener('pageshow',revisit)
    return ()=>window.removeEventListener('pageshow',revisit)
  },[form])
  async function logout() {
    setBusy(true)
    try {
      await api.post('/logout')
      location.replace('/login')
    } catch (failure) {
      if (failure.response?.status===401) location.replace('/login')
      else {setError('Sign-out failed. Please try again.');setBusy(false)}
    }
  }
  return <><header><strong className="brand"><i>R</i> RepoMind <em>AI</em></strong><a href="/setup">Service checks</a></header>
    <main>{error && <p role="alert">{error}</p>}{form?<AccountForm register={path==='/register'}/>:user && path==='/chat'?<React.Suspense fallback={<p>Loading chat…</p>}><Chat/></React.Suspense>:user?<><section className="account">
      <p className="eyebrow">WORKSPACE DASHBOARD</p><h1>Welcome, {user.username}</h1><p>Signed in as {user.email}</p>
      <button disabled={busy} onClick={logout}>{busy?'Signing out…':'Sign out'}</button></section><Repositories/></>:!error && <p role="status">Checking your session…</p>}</main></>
}
createRoot(document.getElementById('root')).render(location.pathname==='/setup'?<Setup/>:<Workspace/>)

