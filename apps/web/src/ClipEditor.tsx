import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadFile, request, type SourceAsset } from './api'
import { PublicationForm } from './PublicationForm'
import type { WorkflowDraft } from './WorkflowPanel'

type Cue = { start: number; end: number; text: string }
type Suggestion = { start: number; end: number; title: string; reason: string }
type Violation = { index: number; kind: string; detail: string }
type Task = { id: string; source_asset_id: string; clip_edit_id: string | null; kind: string; state: string; error: string | null;
  result: { artifact_id?: string; scenes?: {start: number; end: number}[];
    focus?: {focus_x: number; samples: number; found: number; reason: string} } }

export function ClipEditor({ assets, onWorkflow }: { assets: SourceAsset[]; onWorkflow: (draft:WorkflowDraft)=>void }) {
  const [assetId, setAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(30)
  const [mode, setMode] = useState('pad')
  const [focus, setFocus] = useState(0.5)
  const [title, setTitle] = useState('')
  const [captions, setCaptions] = useState<Cue[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [violations, setViolations] = useState<Violation[]>([])
  const [plainScript, setPlainScript] = useState('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [outputUrl, setOutputUrl] = useState('')
  const [previewed, setPreviewed] = useState('')
  const [previewId, setPreviewId] = useState('')
  const [approvedId,setApprovedId] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const selection = useRef('')

  const refresh = useCallback(async () => {
    try { setTasks(await request<Task[]>('/media-tasks')) }
    catch (e) { setMessage(e instanceof Error ? e.message : '작업 조회 실패') }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 5000)
    return () => clearInterval(timer)
  }, [refresh])

  async function act(operation: () => Promise<void>) {
    setBusy(true); setMessage('')
    try { await operation() }
    catch (e) { setMessage(e instanceof Error ? e.message : '요청 실패') }
    finally { setBusy(false) }
  }
  async function loadSource(id: string) {
    selection.current = id
    setAssetId(id); setSourceUrl(''); setSuggestions([]); setCaptions([])
    const asset = assets.find(a => a.id === id)
    setStart(0); setEnd(Math.min(30, Number(asset?.duration_seconds ?? 30)))
    if (!id) return
    await act(async () => {
      const [preview, cues] = await Promise.all([
        request<{url: string}>(`/source-assets/${id}/preview-url`),
        request<Cue[]>(`/source-assets/${id}/transcript`),
      ])
      if (selection.current !== id) return
      setSourceUrl(preview.url); setCaptions(cues)
    })
  }
  function updateCue(index: number, patch: Partial<Cue>) {
    setCaptions(current => current.map((cue, i) => i === index ? {...cue, ...patch} : cue))
  }
  return <section className="clip-editor">
    <h2>롱폼 → 숏폼 편집</h2>
    <p>원본 구간을 고르고 세로 화면·제목·자막을 편집하세요. 저장할 때마다 독립된 결과물을 만듭니다.</p>
    <label>원본 <select value={assetId} disabled={busy} onChange={e => void loadSource(e.target.value)}>
      <option value="">원본 선택</option>
      {assets.filter(a => a.upload_state === 'verified').map(a => <option key={a.id} value={a.id}>{a.original_filename}</option>)}
    </select></label>
    {sourceUrl && <video ref={video} src={sourceUrl} controls preload="metadata" onError={() => setMessage('영상 URL이 만료되면 원본을 다시 선택하세요.')} />}
    {assetId && <>
      <div className="editor-fields">
        <label>시작(초)<input type="number" min="0" step="0.01" value={start} onChange={e => setStart(Number(e.target.value))} /></label>
        <button onClick={() => setStart(video.current?.currentTime ?? start)}>현재 위치를 시작으로</button>
        <label>종료(초)<input type="number" min="0" step="0.01" value={end} onChange={e => setEnd(Number(e.target.value))} /></label>
        <button onClick={() => setEnd(video.current?.currentTime ?? end)}>현재 위치를 종료로</button>
        <label>세로 화면<select value={mode} onChange={e => setMode(e.target.value)}>
          <option value="pad">전체 화면 유지 + 여백</option><option value="crop">화면을 채우도록 자르기</option>
        </select></label>
        {mode === 'crop' && <label>좌우 중심<input type="range" min="0" max="1" step="0.01" value={focus} onChange={e => setFocus(Number(e.target.value))} /></label>}
        <label>화면 제목<input maxLength={120} value={title} onChange={e => setTitle(e.target.value)} /></label>
      </div>
      <p>선택 길이: {(end-start).toFixed(2)}초 · 출력: 1080 × 1920</p>
      <div className="editor-actions">
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'transcribe'})})
          setMessage('로컬 음성 인식을 요청했습니다. 완료 후 대본 다시 읽기를 누르세요.'); await refresh()
        })}>음성 인식</button>
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'scenes'})}); await refresh()
        })}>장면 감지</button>
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'faces'})})
          setMessage('얼굴 위치를 찾고 있습니다. 결과는 제안일 뿐이고 좌우 중심은 바뀌지 않습니다.'); await refresh()
        })}>좌우 중심 제안</button>
        <button disabled={busy} onClick={() => void act(async () => {
          setCaptions(await request<Cue[]>(`/source-assets/${assetId}/transcript`))
        })}>대본 다시 읽기</button>
      </div>
      <details>
        <summary>시간 없는 대본 붙여넣기</summary>
        <p>이미 있는 대본을 원본 음성에 맞춰 시각을 찾습니다. 글자는 그대로 두고 시간만 붙입니다. 유료 호출이 아닙니다.</p>
        <textarea rows={6} maxLength={50000} value={plainScript} placeholder="대본을 붙여넣으세요"
          onChange={e => setPlainScript(e.target.value)} />
        <button disabled={busy || !plainScript.trim()} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/align`, {method:'POST', body: JSON.stringify({text: plainScript})})
          setMessage('대본 정렬을 요청했습니다. 완료 후 대본 다시 읽기를 누르세요.'); await refresh()
        })}>대본 정렬 요청</button>
      </details>
      {violations.length > 0 && <div className="error">
        <p>자막 가독성 문제 {violations.length}건. 렌더에서 줄바꿈과 분할은 자동으로 적용되지만 아래는 사람이 고쳐야 합니다.</p>
        <ul>{violations.map((v,i) => <li key={i}>{v.index + 1}번 자막 · {v.kind} · {v.detail}</li>)}</ul>
      </div>}
      <h3>자막 편집</h3>
      <p>시간은 원본 영상 기준입니다. 선택 구간 밖의 자막은 최종 영상에서 자동으로 제외됩니다.</p>
      {captions.map((cue, index) => <div className="caption-row" key={index}>
        <label>시작(초)<input type="number" min="0" step="0.01" value={cue.start} onChange={e => updateCue(index,{start:Number(e.target.value)})} /></label>
        <label>종료(초)<input type="number" min="0" step="0.01" value={cue.end} onChange={e => updateCue(index,{end:Number(e.target.value)})} /></label>
        <label>자막 내용<textarea rows={2} maxLength={2000} value={cue.text} onChange={e => updateCue(index,{text:e.target.value})} /></label>
        <button onClick={() => setCaptions(current => current.filter((_,i) => i !== index))}>삭제</button>
      </div>)}
      <button onClick={() => setCaptions(current => [...current,{start,end,text:''}])}>자막 추가</button>
      <div className="editor-actions">
        <button disabled={busy} onClick={() => void act(async () => {
          const saved = await request<{violations: Violation[]}>(`/source-assets/${assetId}/transcript`, {method:'PUT', body: JSON.stringify({cues:captions})})
          setViolations(saved.violations)
          setMessage(saved.violations.length ? '저장했습니다. 아래 가독성 문제를 확인하세요.' : '대본을 새 버전으로 저장했습니다.')
        })}>대본 저장</button>
        <button disabled={busy} onClick={() => void act(async () => {
          const report = await request<{violations: Violation[]}>(`/source-assets/${assetId}/subtitle-check`)
          setViolations(report.violations)
          setMessage(report.violations.length ? `${report.violations.length}건을 확인하세요.` : '가독성 문제가 없습니다.')
        })}>자막 가독성 검사</button>
        <button disabled={busy} onClick={() => void act(async () => {
          setSuggestions(await request<Suggestion[]>(`/source-assets/${assetId}/suggestions`))
          setMessage('저장된 대본의 문장 경계로 후보를 만들었습니다. AI 인기도 예측은 아닙니다.')
        })}>구간 후보 찾기</button>
        <button disabled={busy || end <= start || end-start > 180} onClick={() => void act(async () => {
          await request('/clips', {method:'POST', body: JSON.stringify({source_asset_id:assetId, start, end, mode, focus_x:focus, title, cues:captions})})
          setMessage('새 편집본의 렌더를 요청했습니다.'); await refresh()
        })}>숏폼 렌더</button>
      </div>
      <button disabled={busy||end<=start||end-start>180} onClick={()=>{onWorkflow({source_asset_id:assetId,start,end,mode,focus_x:focus,title,cues:captions});setMessage('아래 단계별 제작 화면에 선택 구간을 전달했습니다.')}}>선택 구간을 번역·더빙 단계로 보내기</button>
      {suggestions.map((s,i) => <button key={i} onClick={() => {setStart(s.start);setEnd(s.end);setTitle(s.title)}}>{s.start.toFixed(1)}–{s.end.toFixed(1)}초 · {s.title}</button>)}
    </>}
    {message && <p role="status">{message}</p>}
    <h3>분석·렌더 결과</h3>
    <ul>{tasks.filter(t => !assetId || t.source_asset_id === assetId).map(t => <li key={t.id}>
      {t.kind} · {t.state} {t.error}
      {t.result.scenes?.map((s,i) => <button key={i} onClick={() => {setStart(s.start);setEnd(Math.min(s.end,s.start+180))}}>{s.start.toFixed(1)}–{s.end.toFixed(1)}초</button>)}
      {t.result.focus && <> <span>{t.result.focus.reason}</span>
        {/* 누를 때만 적용합니다. 검출기가 틀리면 맞춰 둔 값을 망칩니다. */}
        <button disabled={busy} onClick={() => {setMode('crop');setFocus(t.result.focus!.focus_x);
          setMessage(`좌우 중심을 ${t.result.focus!.focus_x}로 바꿨습니다. 미리보기로 확인하세요.`)}}>
          이 제안 적용</button></>}
      {t.state === 'failed' && <button disabled={busy} onClick={() => void act(async () => {
        await request(`/media-tasks/${t.id}/retry`, {method:'POST'}); await refresh()
      })}>재시도</button>}
      {t.kind === 'render' && t.clip_edit_id && (['srt','vtt'] as const).map(fmt => <button key={fmt} disabled={busy} onClick={() => void act(async () => {
        await downloadFile(`/clips/${t.clip_edit_id}/subtitles?format=${fmt}`, `clip-${t.clip_edit_id}.${fmt}`)
        setMessage(`자막 ${fmt.toUpperCase()} 파일을 내려받았습니다. 시각은 클립 시작이 0초입니다.`)
      })}>자막 {fmt.toUpperCase()} 내려받기</button>)}
      {t.result.artifact_id && <>
        <button disabled={busy} onClick={() => void act(async () => {
          const p = await request<{url:string}>(`/artifacts/${t.result.artifact_id}/preview`)
          setOutputUrl(p.url); setPreviewed(''); setPreviewId(t.result.artifact_id ?? '')
        })}>최종 영상 보기</button>
        <button disabled={busy || previewed !== t.result.artifact_id} onClick={() => void act(async () => {
          await request(`/artifacts/${t.result.artifact_id}/approve`, {method:'POST'}); setApprovedId(t.result.artifact_id ?? '');setMessage('이 결과물 버전을 승인했습니다. 아래에서 공개 예약을 요청할 수 있습니다.')
        })}>이 버전 승인</button>
      </>}
    </li>)}</ul>
    {approvedId && <PublicationForm artifactId={approvedId} />}
    {outputUrl && <><video src={outputUrl} controls onPlay={() => {
      setPreviewed(previewId)
    }} /><a href={outputUrl} target="_blank" rel="noreferrer">영상 열기·다운로드</a></>}
  </section>
}
