// 용어집. 번역이 꼭 써야 할 표기를 방향(원문 언어 → 목표 언어)마다 둡니다.
// 저장한 용어는 다음 번역 단계부터 적용되고, 이미 끝난 작업의 결과는 바뀌지 않습니다.

import { useCallback, useEffect, useState } from 'react'

import { ApiError, request } from './api'

interface GlossarySummary {
  source_language: string
  target_language: string
  version: number
  term_count: number
}

interface GlossaryDetail extends GlossarySummary {
  entries: Record<string, string>
}

type Row = { source: string; target: string }

const EMPTY: Row = { source: '', target: '' }

function toRows(entries: Record<string, string>): Row[] {
  return Object.entries(entries).map(([source, target]) => ({ source, target }))
}

function toEntries(rows: Row[]): Record<string, string> {
  const entries: Record<string, string> = {}
  for (const row of rows) {
    const source = row.source.trim()
    const target = row.target.trim()
    if (source !== '' && target !== '') entries[source] = target
  }
  return entries
}

export function GlossaryPanel() {
  const [glossaries, setGlossaries] = useState<GlossarySummary[]>([])
  const [source, setSource] = useState('ko')
  const [target, setTarget] = useState('en')
  const [rows, setRows] = useState<Row[]>([EMPTY])
  const [version, setVersion] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadList = useCallback(async () => {
    try {
      setGlossaries(await request<GlossarySummary[]>('/glossaries'))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '용어집 목록을 불러오지 못했습니다.')
    }
  }, [])

  const loadOne = useCallback(async (from: string, to: string) => {
    setMessage(null)
    setError(null)
    try {
      const detail = await request<GlossaryDetail>(`/glossaries/${from}/${to}`)
      setRows(toRows(detail.entries).concat(EMPTY))
      setVersion(detail.version)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setRows([EMPTY])
        setVersion(null)
        return
      }
      setError(cause instanceof Error ? cause.message : '용어집을 불러오지 못했습니다.')
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  useEffect(() => {
    void loadOne(source, target)
  }, [loadOne, source, target])

  function change(index: number, field: keyof Row, value: string) {
    const next = rows.map((row, at) => (at === index ? { ...row, [field]: value } : row))
    // 마지막 줄을 채우면 빈 줄을 하나 더 내어 줍니다.
    if (index === rows.length - 1 && value !== '') next.push(EMPTY)
    setRows(next)
  }

  async function save() {
    setBusy(true)
    setMessage(null)
    setError(null)
    try {
      const saved = await request<GlossaryDetail>(`/glossaries/${source}/${target}`, {
        method: 'PUT',
        body: JSON.stringify({ entries: toEntries(rows) }),
      })
      setVersion(saved.version)
      setRows(toRows(saved.entries).concat(EMPTY))
      setMessage(`용어 ${saved.term_count}개를 저장했습니다 (${saved.version}판). 다음 번역부터 적용됩니다.`)
      await loadList()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '저장에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!window.confirm(`${source} → ${target} 용어집을 지울까요?`)) return
    setBusy(true)
    setError(null)
    try {
      await request(`/glossaries/${source}/${target}`, { method: 'DELETE' })
      setRows([EMPTY])
      setVersion(null)
      setMessage('용어집을 지웠습니다.')
      await loadList()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '삭제에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="glossary">
      <h2>용어집</h2>
      <p>
        채널 이름·제품명처럼 <strong>매번 같게 나와야 하는 말</strong>의 번역 표기를 고정합니다.
        넣는 표기는 글자 그대로라 목표 언어의 어미·관사에 맞춰 변형되지 않고, 찾기는 대소문자를
        가립니다. 원문 언어를 지정하지 않은(자동 감지) 작업에는 적용되지 않습니다.
      </p>
      <p>
        <label>
          원문 언어{' '}
          <input value={source} maxLength={3} size={4}
            onChange={(e) => setSource(e.target.value.trim().toLowerCase())} />
        </label>{' '}
        <label>
          목표 언어{' '}
          <input value={target} maxLength={8} size={6}
            onChange={(e) => setTarget(e.target.value.trim())} />
        </label>{' '}
        {version !== null ? <span>{version}판</span> : <span>아직 없는 용어집입니다.</span>}
      </p>
      {glossaries.length > 0 && (
        <p>
          저장된 용어집:{' '}
          {glossaries.map((item) => (
            <button key={`${item.source_language}-${item.target_language}`} type="button"
              onClick={() => { setSource(item.source_language); setTarget(item.target_language) }}>
              {item.source_language} → {item.target_language} ({item.term_count})
            </button>
          ))}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>원문 표기</th>
            <th>번역문에 넣을 표기</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              <td>
                <input value={row.source} maxLength={80} placeholder="녹화4"
                  onChange={(e) => change(index, 'source', e.target.value)} />
              </td>
              <td>
                <input value={row.target} maxLength={120} placeholder="Recording 4"
                  onChange={(e) => change(index, 'target', e.target.value)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <button type="button" onClick={() => void save()} disabled={busy}>
          {busy ? '저장 중…' : '용어집 저장'}
        </button>{' '}
        {version !== null && (
          <button type="button" onClick={() => void remove()} disabled={busy}>용어집 지우기</button>
        )}
      </p>
      {message !== null && <p>{message}</p>}
      {error !== null && <p className="error">{error}</p>}
    </section>
  )
}
