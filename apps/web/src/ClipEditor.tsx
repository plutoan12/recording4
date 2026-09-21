import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadFile, importSubtitles, request, type EncodingChoice, type ImportResult, type SourceAsset } from './api'
import { PublicationForm } from './PublicationForm'
import type { WorkflowDraft } from './WorkflowPanel'

type Cue = { start: number; end: number; text: string }
type Suggestion = { start: number; end: number; title: string; reason: string }
type Violation = { index: number; kind: string; detail: string }
type Segment = { start: number; end: number; speed?: number }
type Task = { id: string; source_asset_id: string; clip_edit_id: string | null; kind: string; state: string; error: string | null;
  result: { artifact_id?: string; scenes?: {start: number; end: number}[];
    sync?: {offset_seconds:number; framerate_scale:number; clamped:number};
    focus?: {focus_x: number; samples: number; found: number; reason: string};
    clips?: Suggestion[]; rejected?: {first: number; last: number; why: string}[];
    segments?: Segment[]; kept_seconds?: number; removed_seconds?: number; source_seconds?: number;
    storage_key?: string; at?: number } }

export function ClipEditor({ assets, onWorkflow }: { assets: SourceAsset[]; onWorkflow: (draft:WorkflowDraft)=>void }) {
  const [assetId, setAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(30)
  const [mode, setMode] = useState('pad')
  const [focus, setFocus] = useState(0.5)
  const [burn,setBurn] = useState(true)
  const [captionLanguage,setCaptionLanguage] = useState('ko')
  const [title, setTitle] = useState('')
  const [captions, setCaptions] = useState<Cue[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [violations, setViolations] = useState<Violation[]>([])
  const [plainScript, setPlainScript] = useState('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [outputUrl, setOutputUrl] = useState('')
  // 이어 붙일 구간들. 비어 있으면 지금까지처럼 시작~종료 한 구간입니다.
  const [segments, setSegments] = useState<Segment[]>([])
  const [fadeIn, setFadeIn] = useState(0)
  const [fadeOut, setFadeOut] = useState(0)
  const [musicId, setMusicId] = useState('')
  const [musicGain, setMusicGain] = useState(-18)
  const [musicDuck, setMusicDuck] = useState(true)
  const [previewAt, setPreviewAt] = useState(0)
  const [frameUrl, setFrameUrl] = useState('')
  const [previewed, setPreviewed] = useState('')
  const [previewId, setPreviewId] = useState('')
  const [approvedId,setApprovedId] = useState('')
  const [message, setMessage] = useState('')
  // 인코딩을 물어야 하는 파일. used가 있으면 판별기가 고른 것으로 이미 들인 뒤라
  // 글자를 확인하고 되돌릴 수 있게 남겨 둡니다.
  const [pending, setPending] = useState<{file: File; choices: EncodingChoice[]; used?: string} | null>(null)
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
    setSegments([]); setFrameUrl('')
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
  async function bring(file: File, encoding?: string) {
    await act(async () => {
      const imported: ImportResult = await importSubtitles(assetId, file, encoding)
      if (!imported.ok) {
        setPending({file, choices: imported.choices})
        setMessage(imported.message)
        return
      }
      // 판별기가 고른 인코딩이면 다른 후보를 남겨 둡니다. 글자가 깨져도 파일
      // 모양은 멀쩡해서 서버가 못 거릅니다. 사람이 보고 되돌려야 합니다.
      setPending(imported.encoding_detected
        ? {file, used: imported.encoding,
           choices: (imported.choices ?? []).filter(c => c.encoding !== imported.encoding)}
        : null)
      setCaptions(await request<Cue[]>(`/source-assets/${assetId}/transcript`))
      setViolations(imported.violations)
      setMessage(`자막 ${imported.count}개를 대본 ${imported.version}번으로 들였습니다`
        + ` (${imported.encoding}${imported.encoding_detected ? ' 자동 판별' : ''}).`
        + (imported.skipped.length ? ` 뺀 자막 ${imported.skipped.length}개: ${imported.skipped.join(' ')}` : ''))
    })
  }
  function updateCue(index: number, patch: Partial<Cue>) {
    setCaptions(current => current.map((cue, i) => i === index ? {...cue, ...patch} : cue))
  }
  const outputSeconds = segments.length
    ? segments.reduce((total, seg) => total + (seg.end - seg.start) / (seg.speed || 1), 0)
    : Math.max(0, end - start)
  // 렌더와 미리보기가 **같은 설정**을 씁니다. 갈라지면 미리본 것과 다른 결과가 나옵니다.
  const clipSpec = () => ({
    start, end, mode, focus_x: focus, title, burn_subtitles: burn, caption_language: captionLanguage,
    cues: captions, segments, fade_in: fadeIn, fade_out: fadeOut,
    music_asset_id: musicId || null, music_gain_db: musicGain, music_duck: musicDuck,
  })
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
      <p>선택 길이: {(end-start).toFixed(2)}초 · 결과 길이: {outputSeconds.toFixed(2)}초 · 출력: 1080 × 1920</p>
      <details><summary>여러 구간 이어 붙이기 · 무음 빼기 · 페이드 · 배경음악</summary>
        <p>구간을 고르지 않으면 시작~종료를 통째로 씁니다. 고르면 그것들만 순서대로 이어 붙이고, 자막 시각도 이어 붙인 시간축으로 옮깁니다.</p>
        <div className="editor-actions">
          <button disabled={busy||end<=start} onClick={() => setSegments(list => [...list, {start, end, speed: 1}])}>지금 구간 추가</button>
          <button disabled={busy||segments.length===0} onClick={() => setSegments([])}>구간 모두 지우기</button>
          <button disabled={busy} onClick={() => void act(async () => {
            await request(`/source-assets/${assetId}/silence`, {method:'POST', body: JSON.stringify({start, end})})
            setMessage('말이 없는 구간을 찾고 있습니다. 결과는 제안이고, 적용은 아래에서 누릅니다.'); await refresh()
          })}>무음 빼고 남길 구간 제안</button>
        </div>
        <ol>{segments.map((seg, i) => <li key={i}>
          {seg.start.toFixed(2)}~{seg.end.toFixed(2)}초 ({((seg.end-seg.start)/(seg.speed||1)).toFixed(2)}초)
          <label>배속<input type="number" min="0.5" max="4" step="0.1" value={seg.speed ?? 1}
            onChange={e => setSegments(list => list.map((x, j) => j===i ? {...x, speed: Number(e.target.value)} : x))} /></label>
          <button onClick={() => setSegments(list => list.filter((_, j) => j !== i))}>삭제</button>
        </li>)}</ol>
        <div className="editor-fields">
          <label>시작 페이드(초)<input type="number" min="0" max="5" step="0.1" value={fadeIn} onChange={e => setFadeIn(Number(e.target.value))} /></label>
          <label>끝 페이드(초)<input type="number" min="0" max="5" step="0.1" value={fadeOut} onChange={e => setFadeOut(Number(e.target.value))} /></label>
          <label>배경음악 원본<select value={musicId} onChange={e => setMusicId(e.target.value)}>
            <option value="">없음</option>
            {assets.filter(a => a.upload_state === 'verified' && a.id !== assetId).map(a => <option key={a.id} value={a.id}>{a.original_filename}</option>)}
          </select></label>
          {musicId && <>
            <label>배경음악 음량(dB)<input type="number" min="-60" max="0" step="1" value={musicGain} onChange={e => setMusicGain(Number(e.target.value))} /></label>
            <label><input type="checkbox" checked={musicDuck} onChange={e => setMusicDuck(e.target.checked)} /> 말할 때 음량 자동으로 낮추기</label>
          </>}
          <label>미리볼 시각(결과 기준, 초)<input type="number" min="0" step="0.1" value={previewAt} onChange={e => setPreviewAt(Number(e.target.value))} /></label>
        </div>
        <button disabled={busy||previewAt>=outputSeconds} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/preview-frame`, {method:'POST', body: JSON.stringify({at: previewAt, spec: clipSpec()})})
          setMessage('미리보기 한 장을 만들고 있습니다. 아래 작업 목록에서 열 수 있습니다.'); await refresh()
        })}>이 설정으로 한 장 미리보기</button>
        {frameUrl && <img src={frameUrl} alt="편집 설정 미리보기" style={{maxWidth: 240}} />}
      </details>
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
        <summary>자막 파일 가져오기 (SRT·VTT·ASS)</summary>
        <p>밖에서 만든 자막 파일을 대본으로 들입니다. 시각은 파일에 적힌 그대로 씁니다. 원본과 맞는지는 확인하지 않으니 들인 뒤 확인하세요.</p>
        <input type="file" accept=".srt,.vtt,.ass,.ssa,text/plain" disabled={busy} onChange={e => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (file) void bring(file)
        }} />
        {pending && <div className="error">
          {pending.used
            ? <p><b>{pending.used}</b>(으)로 자동 판별해 읽었습니다. <b>대본 글자가 제대로 보이는지 확인하세요.</b> 깨졌다면 아래에서 다시 고르면 새 대본 버전으로 들입니다.</p>
            : <p>이 파일의 인코딩을 알 수 없습니다. <b>글자가 제대로 보이는 것</b>을 고르세요. 잘못 고르면 깨진 채로 저장됩니다.</p>}
          {pending.choices.map(choice => <button key={choice.encoding} disabled={busy}
            onClick={() => void bring(pending.file, choice.encoding)}>
            {choice.encoding}: {choice.preview}
          </button>)}
          <button disabled={busy} onClick={() => setPending(null)}>{pending.used ? '확인했습니다' : '취소'}</button>
        </div>}
      </details>
      <details>
        <summary>시간 없는 대본 붙여넣기</summary>
        <p>이미 있는 대본을 원본 음성에 맞춰 시각을 찾습니다. 글자는 그대로 두고 시간만 붙입니다. 유료 호출이 아닙니다.</p>
        <textarea rows={6} maxLength={50000} value={plainScript} placeholder="대본을 붙여넣으세요"
          onChange={e => setPlainScript(e.target.value)} />
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/transcript/sync`, {method:'POST'})
          setMessage('자막 싱크 보정을 요청했습니다. 끝나면 아래 결과에 옮긴 초가 나옵니다. 대본 다시 읽기를 누르세요.'); await refresh()
        })}>자막 싱크 보정 (원본 음성에 맞추기)</button>
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
      <label>자막 표시<select value={burn?'burn':'track'} onChange={e=>setBurn(e.target.value==='burn')}><option value="burn">영상에 굽기 · 트랙 업로드 안 함</option><option value="track">YouTube 트랙만 · 영상에 굽지 않음</option></select></label>
      <label>자막 언어<input value={captionLanguage} onChange={e=>setCaptionLanguage(e.target.value)} pattern="[a-z]{2,3}" placeholder="ko, en, ja" /></label>
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
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/highlights`, {method:'POST'})
          setMessage('AI에게 구간을 물어봤습니다. 유료 호출이고 결과는 아래 목록에 나옵니다. 끝나면 불러오기를 누르세요.'); await refresh()
        })}>AI 구간 추천 요청 (유료)</button>
        <button disabled={busy} onClick={() => void act(async () => {
          const done = tasks.filter(t => t.source_asset_id === assetId && t.kind === 'highlights' && t.state === 'succeeded')
          const latest = done[done.length - 1]
          if (!latest?.result.clips) { setMessage('끝난 AI 추천이 없습니다. 먼저 요청하고 기다리세요.'); return }
          setSuggestions(latest.result.clips)
          const dropped = latest.result.rejected?.length ?? 0
          setMessage(`AI 추천 ${latest.result.clips.length}건입니다. 버린 후보 ${dropped}건(대본에 없는 번호·겹침·길이). 자를지는 직접 정하세요.`)
        })}>AI 추천 결과 불러오기</button>
        <button disabled={busy || end <= start || end-start > 180} onClick={() => void act(async () => {
          await request('/clips', {method:'POST', body: JSON.stringify({source_asset_id:assetId, ...clipSpec()})})
          setMessage('새 편집본의 렌더를 요청했습니다.'); await refresh()
        })}>숏폼 렌더</button>
      </div>
      <button disabled={busy||end<=start||end-start>180} onClick={()=>{onWorkflow({source_asset_id:assetId,start,end,mode,focus_x:focus,title,burn_subtitles:burn,caption_language:captionLanguage,cues:captions});setMessage('아래 단계별 제작 화면에 선택 구간을 전달했습니다.')}}>선택 구간을 번역·더빙 단계로 보내기</button>
      {suggestions.map((s,i) => <button key={i} onClick={() => {setStart(s.start);setEnd(s.end);setTitle(s.title)}}>{s.start.toFixed(1)}–{s.end.toFixed(1)}초 · {s.title}</button>)}
    </>}
    {message && <p role="status">{message}</p>}
    <h3>분석·렌더 결과</h3>
    <ul>{tasks.filter(t => !assetId || t.source_asset_id === assetId).map(t => <li key={t.id}>
      {t.kind} · {t.state} {t.error}
      {t.result.sync && <span> · {t.result.sync.offset_seconds >= 0 ? '뒤로' : '앞으로'} {Math.abs(t.result.sync.offset_seconds).toFixed(2)}초 옮김
        {t.result.sync.framerate_scale !== 1 && ` · 속도 ${t.result.sync.framerate_scale}배`}
        {t.result.sync.clamped > 0 && ` · 0초로 잘린 자막 ${t.result.sync.clamped}개`}</span>}
      {t.result.scenes?.map((s,i) => <button key={i} onClick={() => {setStart(s.start);setEnd(Math.min(s.end,s.start+180))}}>{s.start.toFixed(1)}–{s.end.toFixed(1)}초</button>)}
      {t.result.focus && <> <span>{t.result.focus.reason}</span>
        {/* 누를 때만 적용합니다. 검출기가 틀리면 맞춰 둔 값을 망칩니다. */}
        <button disabled={busy} onClick={() => {setMode('crop');setFocus(t.result.focus!.focus_x);
          setMessage(`좌우 중심을 ${t.result.focus!.focus_x}로 바꿨습니다. 미리보기로 확인하세요.`)}}>
          이 제안 적용</button></>}
      {t.state === 'failed' && <button disabled={busy} onClick={() => void act(async () => {
        await request(`/media-tasks/${t.id}/retry`, {method:'POST'}); await refresh()
      })}>재시도</button>}
      {t.kind === 'silence' && t.result.segments && <>
        <p>남길 구간 {t.result.segments.length}개 · 남김 {t.result.kept_seconds}초 / 원본 {t.result.source_seconds}초 (뺀 시간 {t.result.removed_seconds}초)</p>
        <button disabled={busy} onClick={() => {
          setSegments((t.result.segments ?? []).map(seg => ({...seg, speed: 1})))
          setMessage('제안한 구간을 편집기에 넣었습니다. 확인하고 고친 뒤 저장하세요.')
        }}>제안 구간 적용</button>
      </>}
      {t.kind === 'preview' && t.result.storage_key && <button disabled={busy} onClick={() => void act(async () => {
        const found = await request<{url:string}>(`/media-tasks/${t.id}/preview-url`)
        setFrameUrl(found.url); setMessage('미리보기를 불러왔습니다. 위 편집 설정 칸에서 볼 수 있습니다.')
      })}>미리보기 보기</button>}
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
