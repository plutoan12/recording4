import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadFile, importSubtitles, request, type EncodingChoice, type ImportResult, type SourceAsset } from './api'
import { PublicationForm } from './PublicationForm'
import { SubtitlePreview } from './SubtitlePreview'
import type { WorkflowDraft } from './WorkflowPanel'

type Word = { start: number; end: number; text: string }
// words는 정렬기가 준 단어 시각입니다. 글자를 고치면 맞지 않으므로 비웁니다.
type Cue = { start: number; end: number; text: string; words?: Word[] | null }
type Suggestion = { start: number; end: number; title: string; reason: string }
type Violation = { index: number; kind: string; detail: string }
type Template = { name: string; label: string; description: string; category: string; category_label: string; sample: string;
  font_name: string; font_size: number; bold: boolean; italic: boolean; primary_color: string; outline_color: string; box_color: string;
  outline: number; outline2: number; outline2_color: string; shadow: number; glow: number; angle: number;
  hollow: boolean; extrude: number; extrude_color: string; accent_color: string; box_radius: number;
  border_style: 'outline' | 'box' | 'box-outline'; letter_spacing: number; prefix: string; suffix: string;
  animation: string; animation_ms: number | null; animation_label: string;
  gradient_color: string; gradient_direction: 'vertical' | 'horizontal' }
type AnimationChoice = { name: string; label: string }
type PacingChoice = { name: string; label: string }
type PresetChoice = { name: string; label: string; pack: string; pack_label: string; summary: string; editable: boolean }
type StickerKind = { kind: string; label: string; images?: string[] }
// 워커의 pipeline.subtitle_stickers.Sticker와 같은 항목입니다. 시각은 원본 영상 기준 초입니다.
type Sticker = { kind: string; image?: string | null; x: number; y: number; size: number; start: number; end: number | null;
  color: string; outline_color: string; outline: number; angle: number; animation: string }

// 워커의 ASS 움직임을 CSS 키프레임(styles.css의 r4-motion-*)으로 흉내 냅니다. 타자기·단어별·
// 노래방은 글자 단위라 CSS로는 비슷한 느낌(가리개 걷기·페이드)만 보여 줍니다.
const MOTION_KEYFRAMES: Record<string, string> = {
  fade: 'r4-motion-fade', pop: 'r4-motion-pop', bounce: 'r4-motion-bounce', 'slide-up': 'r4-motion-slide-up',
  'slide-down': 'r4-motion-slide-down', zoom: 'r4-motion-zoom', wiggle: 'r4-motion-wiggle', pulse: 'r4-motion-pulse',
  typewriter: 'r4-motion-typewriter', 'word-pop': 'r4-motion-typewriter', karaoke: 'r4-motion-fade' }
function motionStyle(animation: string): React.CSSProperties {
  const name = MOTION_KEYFRAMES[animation]
  return name ? { animation: `${name} 2.6s ease-out infinite` } : {}
}

// 워커가 libass로 굽는 모양을 CSS로 흉내 냅니다. 글꼴 이름은 Google Fonts 이름으로 바꾸고
// 픽셀 글꼴은 고정폭으로 대신합니다. 정확한 모양은 미리보기 시트(r4-subtitles sheet)를 봅니다.
const FONT_ALIASES: Record<string, string> = { 'Nanum Pen': 'Nanum Pen Script', 'Galmuri11 Regular': 'monospace', 'Galmuri9 Regular': 'monospace',
  // Google Fonts에 없는 글꼴은 비슷한 굵기의 Google 글꼴로 대신 보여 줍니다. 실제 렌더는 워커의 원래 글꼴입니다.
  'Jalnan': 'Black Han Sans', 'Cafe24 Ssurround': 'Jua', 'Cafe24 Simplehae': 'Jua', 'Gmarket Sans': 'Gothic A1', 'Pretendard': 'Gothic A1', 'Wanted Sans': 'Gothic A1',
  'S-Core Dream 6 Bold': 'Gothic A1', 'S-Core Dream 8 Heavy': 'Black Han Sans', 'NanumSquareRound': 'Jua', 'TmonMonsori': 'Black Han Sans', 'Swagger TTF': 'Do Hyeon',
  'SUIT': 'Gothic A1', 'BM HANNA Pro': 'Do Hyeon', 'BM Euljiro oraeorae': 'Gugi', 'Ownglyph MoogungChae': 'Gaegu', 'Maplestory': 'Jua', 'NEXON Lv1 Gothic OTF': 'Gothic A1' }
function cssColor(hex: string): string {
  // #RRGGBBAA(AA=불투명도)는 CSS도 같은 뜻이라 그대로 씁니다.
  return hex
}
function templatePreviewStyle(t: Template): React.CSSProperties {
  const family = FONT_ALIASES[t.font_name] ?? t.font_name
  const size = Math.max(14, Math.round(t.font_size / 3))
  const stroke = Math.max(0, Math.round(t.outline / 2.5))
  const shadows: string[] = []
  if (t.border_style === 'outline' && stroke > 0) shadows.push(`0 0 0 ${stroke}px ${cssColor(t.outline_color)}`)
  if (t.border_style === 'outline' && t.outline2 > 0) {
    // text-shadow에는 번짐 폭이 없어 여덟 방향으로 같은 그림자를 두어 바깥 테두리를 흉내 냅니다.
    const ring = stroke + Math.max(1, Math.round(t.outline2 / 2.5))
    for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1],[0.7,0.7],[-0.7,0.7],[0.7,-0.7],[-0.7,-0.7]])
      shadows.push(`${(dx*ring).toFixed(1)}px ${(dy*ring).toFixed(1)}px 0 ${cssColor(t.outline2_color)}`)
  }
  if (t.glow > 0) shadows.push(`0 0 ${Math.round(t.glow * 1.5)}px ${cssColor(t.outline_color)}`, `0 0 ${Math.round(t.glow * 3)}px ${cssColor(t.outline_color)}`)
  if (t.shadow > 0 && t.border_style === 'outline') shadows.push(`${Math.round(t.shadow)}px ${Math.round(t.shadow)}px 0 rgba(0,0,0,.6)`)
  // 입체 돌출: 그림자를 1px씩 밀어 쌓습니다(워커의 -Extrude 층과 같은 방식).
  for (let d = 1; d <= Math.round(t.extrude / 2); d++) shadows.push(`${d}px ${d}px 0 ${cssColor(t.extrude_color)}`)
  // 그라데이션은 글자 모양으로 자른 배경으로 흉내 냅니다. 속 빈 글자는 선 색이 흐르는데
  // CSS로는 못 하므로 시작 색 선만 보여 줍니다.
  const gradient = t.gradient_color && !t.hollow
    ? `linear-gradient(${t.gradient_direction === 'horizontal' ? 'to right' : 'to bottom'}, ${cssColor(t.primary_color)}, ${cssColor(t.gradient_color)})`
    : undefined
  const style: React.CSSProperties = {
    fontFamily: `'${family}', 'Noto Sans KR', sans-serif`,
    fontSize: `${size}px`,
    fontWeight: t.bold ? 700 : 400,
    fontStyle: t.italic ? 'italic' : 'normal',
    // 속 빈 글자는 채움을 투명으로 두고 선만 보입니다.
    color: t.hollow || gradient ? 'transparent' : cssColor(t.primary_color),
    backgroundImage: gradient,
    WebkitBackgroundClip: gradient ? 'text' : undefined,
    backgroundClip: gradient ? 'text' : undefined,
    letterSpacing: `${t.letter_spacing / 3}px`,
    WebkitTextStroke: t.border_style === 'outline' && stroke > 0 ? `${stroke}px ${cssColor(t.outline_color)}` : undefined,
    paintOrder: 'stroke fill',
    textShadow: shadows.length ? shadows.join(', ') : undefined,
    padding: t.border_style !== 'outline' ? `${Math.round(t.outline / 2)}px ${Math.round(t.outline)}px` : '2px 4px',
    background: t.border_style !== 'outline' ? cssColor(t.box_color) : undefined,
    border: t.border_style === 'box-outline' ? `${Math.max(1, stroke)}px solid ${cssColor(t.outline_color)}` : undefined,
    borderRadius: t.border_style !== 'outline' ? Math.max(4, Math.round(t.box_radius / 2.5)) : undefined,
    display: 'inline-block',
    transform: t.angle ? `rotate(${-t.angle}deg)` : undefined,
    ...motionStyle(t.animation),
  }
  return style
}
// `[[...]]` 강조 표기를 조각으로 나눕니다. 워커의 pipeline.subtitle_markup과 같은 규칙입니다.
function splitMarkup(text: string): { piece: string; accent: boolean }[] {
  const parts: { piece: string; accent: boolean }[] = []
  const re = /\[\[(.*?)(?:\]\]|$)/gs
  let cursor = 0
  for (const m of text.matchAll(re)) {
    if (m.index! > cursor) parts.push({ piece: text.slice(cursor, m.index).replaceAll(']]', ''), accent: false })
    if (m[1]) parts.push({ piece: m[1], accent: true })
    cursor = m.index! + m[0].length
  }
  if (cursor < text.length) parts.push({ piece: text.slice(cursor).replaceAll(']]', ''), accent: false })
  return parts.filter(p => p.piece)
}
function TemplatePreview({ template, animation }: { template: Template; animation?: string }) {
  const text = `${template.prefix ? template.prefix + ' ' : ''}${template.sample || template.label}${template.suffix ? ' ' + template.suffix : ''}`
  const style = templatePreviewStyle(animation ? { ...template, animation } : template)
  const accent = template.accent_color ? cssColor(template.accent_color) : undefined
  return <div className="template-preview"><span style={style}>{splitMarkup(text).map((p, i) => accent && p.accent
    ? <span key={i} style={template.hollow ? { WebkitTextStroke: style.WebkitTextStroke ? `${String(style.WebkitTextStroke).split(' ')[0]} ${accent}` : undefined } : { color: accent }}>{p.piece}</span>
    : <span key={i}>{p.piece}</span>)}</span></div>
}
type Task = { id: string; source_asset_id: string; clip_edit_id: string | null; kind: string; state: string; error: string | null;
  result: { artifact_id?: string; scenes?: {start: number; end: number}[]; highlights?: {start:number; end:number; score:number; speech_ratio:number; scene_cuts:number}[]; sync?: {offset_seconds:number; framerate_scale:number; clamped:number} } }

export function ClipEditor({ assets, onWorkflow }: { assets: SourceAsset[]; onWorkflow: (draft:WorkflowDraft)=>void }) {
  const [assetId, setAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(30)
  const [mode, setMode] = useState('pad')
  const [focus, setFocus] = useState(0.5)
  const [burn,setBurn] = useState(true)
  const [trimSilence,setTrimSilence] = useState(false)
  const [autoFrame,setAutoFrame] = useState(false)
  const [denoise,setDenoise] = useState('')
  const [captionLanguage,setCaptionLanguage] = useState('ko')
  const [template,setTemplate] = useState('default')
  const [templates,setTemplates] = useState<Template[]>([])
  // 빈 값이면 템플릿의 움직임을 그대로 씁니다.
  const [animation,setAnimation] = useState('')
  const [pacing,setPacing] = useState('')
  const [pacings,setPacings] = useState<PacingChoice[]>([])
  const [preset,setPreset] = useState('')
  const [presets,setPresets] = useState<PresetChoice[]>([])
  const presetFile = useRef<HTMLInputElement>(null)
  const [animations,setAnimations] = useState<AnimationChoice[]>([])
  const [stickerKinds,setStickerKinds] = useState<StickerKind[]>([])
  const [stickers,setStickers] = useState<Sticker[]>([])
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
  // 프리셋 목록은 파일을 올리거나 지운 뒤에도 다시 읽습니다.
  const loadPresets = useCallback(
    () => request<PresetChoice[]>('/subtitle-presets').then(setPresets).catch(() => setPresets([])),
    [],
  )

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 5000)
    return () => clearInterval(timer)
  }, [refresh])
  useEffect(() => {
    // 내장 템플릿 목록은 서버가 정합니다. 못 받으면 기본 템플릿만 남겨 렌더는 계속할 수 있게 합니다.
    request<Template[]>('/subtitle-templates').then(setTemplates).catch(() => setTemplates([]))
    request<AnimationChoice[]>('/subtitle-animations').then(setAnimations).catch(() => setAnimations([]))
    void loadPresets()
    request<PacingChoice[]>('/subtitle-pacings').then(setPacings).catch(() => setPacings([]))
    request<StickerKind[]>('/stickers').then(setStickerKinds).catch(() => setStickerKinds([]))
  }, [])

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
  function updateSticker(index: number, patch: Partial<Sticker>) {
    setStickers(current => current.map((s, i) => i === index ? {...s, ...patch} : s))
  }
  // 정확 미리보기에 넣을 스티커: 시각을 선택 구간 기준(0초)으로 옮기고 이미지는 뺍니다(합성 단계).
  const previewStickers = stickers.filter(s => s.kind !== 'image').map(s => ({...s, image: undefined, start: 0, end: null}))
  function updateCue(index: number, patch: Partial<Cue>) {
    setCaptions(current => current.map((cue, i) => i === index ? {...cue, ...patch, ...(patch.text !== undefined && patch.text !== cue.text ? {words: null} : {})} : cue))
  }
  const chosenPreset = presets.find(p => p.name === preset)

  async function savePresetFile(file: File) {
    try {
      const body = JSON.parse(await file.text())
      const saved = await request<{name:string}>('/subtitle-presets', {method:'POST', body: JSON.stringify(body)})
      await loadPresets()
      setPreset(saved.name)
      setMessage(`프리셋 ${saved.name}을 내 프리셋으로 넣었습니다.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '프리셋 파일을 읽지 못했습니다.')
    }
  }

  async function removePreset() {
    if (!chosenPreset?.editable) return
    try {
      await request(`/subtitle-presets/${chosenPreset.name}`, {method:'DELETE'})
      setPreset('')
      await loadPresets()
      setMessage(`프리셋 ${chosenPreset.name}을 지웠습니다.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '프리셋을 지우지 못했습니다.')
    }
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
      <label><input type="checkbox" checked={trimSilence} onChange={e => setTrimSilence(e.target.checked)} /> 말 없는 구간 자동으로 잘라내기
        <span className="hint">말을 찾아(VAD) 사이의 침묵을 빼고 이어 붙입니다. 0.6초보다 짧은 침묵은 그대로 두고, 말 앞뒤로 0.12초는 남깁니다. 자막·스티커 시각도 함께 옮깁니다. 말을 하나도 못 찾으면 자르지 않습니다.</span></label>
      <label><input type="checkbox" checked={autoFrame} onChange={e => setAutoFrame(e.target.checked)} disabled={mode !== 'crop'} /> 얼굴을 따라 화면 중심 움직이기
        <span className="hint">{mode === 'crop'
          ? '세로로 자를 때 얼굴 위치를 따라 좌우 중심이 움직입니다. 고개를 까딱하는 정도(화면 폭 6%)는 무시하고, 초당 화면 폭의 25%까지만 따라가 화면이 떨지 않습니다. 얼굴을 못 찾으면 아래 가로 중심 값을 그대로 씁니다. 사람이 여럿이면 가장 큰 얼굴을 따라갑니다.'
          : '잘라내기(crop)에서만 씁니다. 여백 채우기(pad)는 화면 전체를 남기므로 따라갈 것이 없습니다.'}</span></label>
      <label>음성 잡음 제거
        <select value={denoise} onChange={e => setDenoise(e.target.value)}>
          <option value="">쓰지 않음</option>
          <option value="soft">약하게</option>
          <option value="strong">강하게</option>
        </select>
        <span className="hint">FFmpeg 내장 필터라 추가 설치가 없습니다. 강하게는 잡음을 더 깎지만 목소리도 같이 깎일 수 있습니다.</span></label>
      <div className="editor-actions">
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'transcribe'})})
          setMessage('로컬 음성 인식을 요청했습니다. 완료 후 대본 다시 읽기를 누르세요.'); await refresh()
        })}>음성 인식</button>
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'scenes'})}); await refresh()
        })}>장면 감지</button>
        <button disabled={busy} onClick={() => void act(async () => {
          await request(`/source-assets/${assetId}/analyze`, {method:'POST', body: JSON.stringify({kind:'highlights'})})
          setMessage('숏폼 후보 구간을 찾고 있습니다. 아래 결과에 나오면 눌러서 구간을 잡으세요.'); await refresh()
        })}>숏폼 구간 추천</button>
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
      <label>자막 템플릿<select value={template} disabled={!burn} onChange={e=>setTemplate(e.target.value)}>
        {templates.length === 0 && <option value="default">기본 (default)</option>}
        {Array.from(new Set(templates.map(t => t.category_label))).map(group => <optgroup key={group} label={group}>
          {templates.filter(t => t.category_label === group).map(t => <option key={t.name} value={t.name} title={t.description}>{t.label} ({t.name})</option>)}
        </optgroup>)}
      </select></label>
      <label>자막 끊기<select value={pacing} disabled={!burn} onChange={e=>setPacing(e.target.value)}>
        <option value="">서버 기본값</option>
        {pacings.map(p => <option key={p.name} value={p.name}>{p.label}</option>)}
      </select></label>
      <label>모션 프리셋<select value={preset} disabled={!burn} onChange={e=>setPreset(e.target.value)}>
        <option value="">쓰지 않음(템플릿 값)</option>
        {[...new Map(presets.map(p => [p.pack, p.pack_label])).entries()].map(([pack, packLabel]) => (
          <optgroup key={pack} label={packLabel}>
            {presets.filter(p => p.pack === pack).map(p => <option key={p.name} value={p.name} title={p.summary}>{p.label}</option>)}
          </optgroup>
        ))}
      </select></label>
      <div className="preset-files">
        <button type="button" disabled={!preset} onClick={() => void downloadFile(`/subtitle-presets/${preset}/file`, `${preset}.json`)}>이 프리셋 파일 받기</button>
        <button type="button" disabled={!chosenPreset} onClick={() => void downloadFile(`/subtitle-preset-packs/${chosenPreset?.pack}`, `r4-presets-${chosenPreset?.pack}.zip`)}>{chosenPreset ? `${chosenPreset.pack_label} 전체 받기` : '팩 전체 받기'}</button>
        <button type="button" onClick={() => presetFile.current?.click()}>프리셋 올리기</button>
        {chosenPreset?.editable && <button type="button" onClick={() => void removePreset()}>내 프리셋 지우기</button>}
        <input ref={presetFile} type="file" accept="application/json,.json" hidden onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void savePresetFile(file) }} />
      </div>
      <label>자막 움직임<select value={animation} disabled={!burn||!!preset} onChange={e=>setAnimation(e.target.value)}>
        <option value="">템플릿 기본{(() => { const chosen = templates.find(t => t.name === template); return chosen ? ` (${chosen.animation_label})` : '' })()}</option>
        {animations.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
      </select></label>
      {burn && (() => { const chosen = templates.find(t => t.name === template); return chosen ? <div className="template-chosen">
        <TemplatePreview template={chosen} animation={animation || undefined} />
        <SubtitlePreview template={chosen.name} animation={animation || undefined} preset={preset || undefined} pacing={pacing || undefined} text={captions.find(c => c.text.trim())?.text.split('\n')[0]} stickers={previewStickers} />
        <p>{chosen.description} 영상에 굽는 자막의 모양이며 SRT·VTT 파일에는 영향이 없습니다. 위 첫 줄은 CSS 근사이고, 아래 세로 화면은 워커와 같은 libass 렌더(정확 미리보기)입니다.{chosen.accent_color && ' 자막 내용에서 [[이렇게]] 감싼 부분은 강조 색으로 그려지고, 파일에는 괄호 없이 나갑니다.'}{(animation || preset || chosen.animation !== 'none') && ' 움직임은 자막마다 시작 시각에 맞춰 붙고 화면 제목에는 붙지 않습니다.'}{preset && ' 모션 프리셋을 고르면 움직임 선택보다 먼저 쓰입니다.'}{pacing === 'shortform' && ' 숏폼 끊기는 대본의 단어 시각에 맞춰 한 줄로 짧게 나눕니다. 글자를 고친 자막은 글자 수로 나눕니다.'}</p>
      </div> : null })()}
      {burn && templates.length > 0 && <details className="template-gallery"><summary>템플릿 전체 미리보기 ({templates.length}종)</summary>
        <div className="template-grid">{templates.map(t => <button type="button" key={t.name} className={t.name === template ? 'selected' : ''} onClick={() => setTemplate(t.name)} title={t.description}>
          <TemplatePreview template={t} /><small>{t.label}</small>
        </button>)}</div>
      </details>}
      {burn && <details className="sticker-panel" open={stickers.length > 0}>
        <summary>스티커 ({stickers.length})</summary>
        <p>화살표·반짝이·말풍선 같은 장식을 자막 위에 얹습니다. 자리는 화면 비율(0~1), 크기는 px, 시각은 원본 영상 기준 초이고 비우면 구간 끝까지입니다. 이미지(PNG)는 워커의 스티커 디렉터리에 있는 파일만 쓸 수 있고 움직임이 붙지 않습니다.</p>
        {stickers.map((s, index) => <div className="sticker-row" key={index}>
          <label>종류<select value={s.kind} onChange={e => updateSticker(index, {kind: e.target.value, image: e.target.value === 'image' ? (stickerKinds.find(k => k.kind === 'image')?.images?.[0] ?? null) : null})}>
            {stickerKinds.map(k => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select></label>
          {s.kind === 'image' && <label>파일<select value={s.image ?? ''} onChange={e => updateSticker(index, {image: e.target.value || null})}>
            <option value="">(없음)</option>
            {(stickerKinds.find(k => k.kind === 'image')?.images ?? []).map(name => <option key={name} value={name}>{name}</option>)}
          </select></label>}
          <label>가로 위치<input type="number" min="0" max="1" step="0.05" value={s.x} onChange={e => updateSticker(index, {x: Number(e.target.value)})} /></label>
          <label>세로 위치<input type="number" min="0" max="1" step="0.05" value={s.y} onChange={e => updateSticker(index, {y: Number(e.target.value)})} /></label>
          <label>크기(px)<input type="number" min="16" max="1080" step="8" value={s.size} onChange={e => updateSticker(index, {size: Number(e.target.value)})} /></label>
          <label>시작(초)<input type="number" min="0" step="0.1" value={s.start} onChange={e => updateSticker(index, {start: Number(e.target.value)})} /></label>
          <label>종료(초)<input type="number" min="0" step="0.1" value={s.end ?? ''} onChange={e => updateSticker(index, {end: e.target.value === '' ? null : Number(e.target.value)})} /></label>
          {s.kind !== 'image' && <>
            <label>색<input type="color" value={s.color.slice(0, 7)} onChange={e => updateSticker(index, {color: e.target.value.toUpperCase()})} /></label>
            <label>외곽선 색<input type="color" value={s.outline_color.slice(0, 7)} onChange={e => updateSticker(index, {outline_color: e.target.value.toUpperCase()})} /></label>
            <label>기울기<input type="number" min="-180" max="180" step="5" value={s.angle} onChange={e => updateSticker(index, {angle: Number(e.target.value)})} /></label>
            <label>움직임<select value={s.animation} onChange={e => updateSticker(index, {animation: e.target.value})}>
              {animations.filter(a => !['typewriter', 'word-pop', 'karaoke'].includes(a.name)).map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
            </select></label>
          </>}
          <button onClick={() => setStickers(current => current.filter((_, i) => i !== index))}>삭제</button>
        </div>)}
        <button onClick={() => setStickers(current => [...current, {kind: 'arrow-down', x: 0.5, y: 0.3, size: 160, start, end: null, color: '#FFE14D', outline_color: '#111111', outline: 2, angle: 0, animation: 'bounce'}])}>스티커 추가</button>
      </details>}
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
          await request('/clips', {method:'POST', body: JSON.stringify({source_asset_id:assetId, start, end, mode, focus_x:focus, title, burn_subtitles:burn, caption_language:captionLanguage, subtitle_template:template, subtitle_animation:animation || null, subtitle_preset:preset || null, subtitle_pacing:pacing || null, cues:captions, stickers, silence: trimSilence ? {} : null, reframe: autoFrame && mode === 'crop' ? {} : null, denoise: denoise || null})})
          setMessage('새 편집본의 렌더를 요청했습니다.'); await refresh()
        })}>숏폼 렌더</button>
      </div>
      <button disabled={busy||end<=start||end-start>180} onClick={()=>{onWorkflow({source_asset_id:assetId,start,end,mode,focus_x:focus,title,burn_subtitles:burn,caption_language:captionLanguage,subtitle_template:template,subtitle_animation:animation||undefined,subtitle_preset:preset||undefined,subtitle_pacing:pacing||undefined,cues:captions,stickers,silence:trimSilence?{}:undefined,reframe:autoFrame&&mode==='crop'?{}:undefined,denoise:denoise||undefined});setMessage('아래 단계별 제작 화면에 선택 구간을 전달했습니다.')}}>선택 구간을 번역·더빙 단계로 보내기</button>
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
      {t.result.highlights?.map((h,i) => <button key={i} title={`말 ${(h.speech_ratio*100).toFixed(0)}% · 장면 전환 ${h.scene_cuts}회`}
        onClick={() => {setStart(h.start);setEnd(h.end)}}>{h.start.toFixed(1)}–{h.end.toFixed(1)}초 · {(h.score*100).toFixed(0)}점</button>)}
      {t.kind === 'highlights' && t.state === 'succeeded' && !t.result.highlights?.length &&
        <span> · 추천할 구간이 없습니다(말이 거의 없는 영상).</span>}
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
