import axios from 'axios'

export const api = axios.create({
  baseURL: '/api/auth',
  timeout: 12000,
  headers: {'X-RepoMind-CSRF': '1'}
})

