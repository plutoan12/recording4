import { useCallback, useEffect, useState } from 'react'

import {
  ApiError,
  type Job,
  type SourceAsset,
  getToken,
  listAssets,
  listJobs,
  login,
  setToken,
  uploadSource,
} from './api'

import { ClipEditor } from './ClipEditor'
import { WorkflowPanel, type WorkflowDraft } from './WorkflowPanel'

const REFRESH_MS = 5000

export function App() {
  const [authed, setAuthed] = useState(getToken() !== null)
  return <main>{authed ? <Dashboard onSignOut={() => setAuthed(false)} /> : <Login onSuccess={() => setAuthed(true)} />}</main>
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await login(email, password)
      onSuccess()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '로그인에 실패했습니다.')
    }
  }

  return (
    <>
      <h1>recording4 관리화면</h1>
      <form className="login" onSubmit={submit}>
        <label>
          이메일
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error !== null && <p className="error">{error}</p>}
        <button type="submit">로그인</button>
      </form>
    </>
  )
}

function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const [assets, setAssets] = useState<SourceAsset[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [workflowDraft, setWorkflowDraft] = useState<WorkflowDraft|null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [nextAssets, nextJobs] = await Promise.all([listAssets(), listJobs()])
      setAssets(nextAssets)
      setJobs(nextJobs)
      setError(null)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setToken(null)
        onSignOut()
        return
      }
      setError(cause instanceof Error ? cause.message : '목록을 불러오지 못했습니다.')
    }
  }, [onSignOut])

  useEffect(() => {
    void refresh()
    // 워커가 파일 검사를 끝내면 상태가 바뀌므로 주기적으로 다시 읽습니다.
    const timer = setInterval(() => void refresh(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [refresh])

  async function onUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file === undefined) return
    setBusy(true)
    setError(null)
    try {
      await uploadSource(file)
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '업로드에 실패했습니다.')
    } finally {
      setBusy(false)
      event.target.value = ''
    }
  }


  return (
    <>
      <h1>작업 현황</h1>
      <p>
        <label>
          원본 등록{' '}
          <input type="file" accept="video/*" onChange={onUpload} disabled={busy} />
        </label>{' '}
        <button
          type="button"
          onClick={() => {
            setToken(null)
            onSignOut()
          }}
        >
          로그아웃
        </button>
      </p>
      {error !== null && <p className="error">{error}</p>}

      <h2>원본</h2>
      <table>
        <thead>
          <tr>
            <th>파일</th>
            <th>상태</th>
            <th>길이(초)</th>
            <th>해상도</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id}>
              <td>{asset.original_filename}</td>
              <td className="state">
                {asset.upload_state}
                {asset.probe_error !== null && <div className="error">{asset.probe_error}</div>}
              </td>
              <td>{asset.duration_seconds ?? '-'}</td>
              <td>{asset.width !== null ? `${asset.width}×${asset.height}` : '-'}</td>
              <td>
                아래 제작 양식에서 선택
              </td>
            </tr>
          ))}
          {assets.length === 0 && (
            <tr>
              <td colSpan={5}>등록된 원본이 없습니다.</td>
            </tr>
          )}
        </tbody>
      </table>

      <ClipEditor assets={assets} onWorkflow={setWorkflowDraft} />
      <WorkflowPanel assets={assets} jobs={jobs} draft={workflowDraft} onCreated={refresh} />

      <h2>작업</h2>
      <table>
        <thead>
          <tr>
            <th>대상 언어</th>
            <th>상태</th>
            <th>단계</th>
            <th>사유</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.target_language}</td>
              <td className="state">{job.state}</td>
              <td>{job.current_stage ?? '-'}</td>
              <td>{job.state_reason ?? '-'}</td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr>
              <td colSpan={4}>작업이 없습니다.</td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  )
}
