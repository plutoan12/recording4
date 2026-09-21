import { useCallback, useEffect, useState } from 'react'
import { downloadFile, request, type Job, type SourceAsset } from './api'
import { PublicationForm } from './PublicationForm'

export type WorkflowDraft = {source_asset_id:string; start:number; end:number; mode:string; focus_x:number;
  title:string; burn_subtitles?:boolean; caption_language?:string; cues:{start:number;end:number;text:string}[]}
type Cue = {start:number;end:number;text:string}
type Detail = {id:string;state:string;stage:string|null;reason:string|null;artifact_id:string|null;approval_id:string|null;
  options:Record<string,unknown>;cues:Cue[];translated:Cue[];translation_qa?:{index:number;issues:string[]}[];
  style_warnings?:{kind:string;message:string;registers:{label:string;cue_numbers:number[]}[]}[];
  stages:{id:string;name:string;state:string;attempt:number;uncertain:boolean;estimated_cost:string|null}[]}
type Publication = {id:string;state:string;title:string;video_id:string|null;publish_at:string;error:string|null}
type Configuration = {paid_enabled:boolean;translation_provider:string;translation_configured:boolean;translation_refine_enabled:boolean;speech_configured:boolean;
  lipsync_configured:boolean;youtube_configured:boolean;youtube_channel_id:string|null;
  languages:{code:string;label:string;tier:number}[];sources:string[];directions:[string,string][]}

export function WorkflowPanel({assets,jobs,draft,onCreated}:{assets:SourceAsset[];jobs:Job[];draft:WorkflowDraft|null;onCreated:()=>Promise<void>}) {
  const [asset,setAsset]=useState('')
  const [audio,setAudio]=useState('subtitles')
  const [burn,setBurn] = useState(true)
  const [sourceLanguage,setSourceLanguage] = useState('ko')
  const [target,setTarget]=useState('en')
  const [voice,setVoice]=useState('')
  const [lip,setLip]=useState(false)
  const [budget,setBudget]=useState('0')
  const [monthly,setMonthly]=useState('')
  const [selected,setSelected]=useState('')
  const [detail,setDetail]=useState<Detail|null>(null)
  const [translated,setTranslated]=useState<Cue[]>([])
  const [publications,setPublications]=useState<Publication[]>([])
  const [config,setConfig]=useState<Configuration|null>(null)
  const [url,setUrl]=useState('')
  const [played,setPlayed]=useState(false)
  const [message,setMessage]=useState('')
  const [busy,setBusy]=useState(false)
  const [useClip,setUseClip]=useState(false)
  useEffect(()=>{if(draft){setAsset(draft.source_asset_id);setBurn(draft.burn_subtitles??true);setSourceLanguage(draft.caption_language??'ko');setUseClip(true)}},[draft])
  // 언어 목록과 방향은 서버 설정(pipeline.languages)에서만 옵니다. 여기에 언어를 적지 않습니다.
  const languages = config?.languages ?? []
  const label = (code:string)=>languages.find(l=>l.code===code)?.label ?? code
  const sourceOptions = languages.filter(l=>(config?.sources??[]).includes(l.code))
  const targetOptions = languages.filter(l=>l.code!==sourceLanguage && (config?.directions??[]).some(([s,t])=>t===l.code && (!sourceLanguage || s===sourceLanguage)))
  useEffect(()=>{if(targetOptions.length && !targetOptions.some(l=>l.code===target)) setTarget(targetOptions[0].code)},[targetOptions,target])
  const refresh = useCallback(async ()=>{
    try {
      const [c,p,d] = await Promise.all([
        request<Configuration>('/workflow/configuration'), request<Publication[]>('/publications'),
        selected ? request<Detail>(`/jobs/${selected}/workflow`) : Promise.resolve(null),
      ])
      setConfig(c);setPublications(p);setDetail(d)
    } catch(e){setMessage(e instanceof Error?e.message:'상태 조회 실패')}
  },[selected])
  useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>clearInterval(timer)},[refresh])
  async function act(action:()=>Promise<void>){setBusy(true);setMessage('');try{await action();await refresh();await onCreated()}catch(e){setMessage(e instanceof Error?e.message:'요청 실패')}finally{setBusy(false)}}
  async function grab(path:string,name:string,done:string){
    setBusy(true);setMessage('')
    try{await downloadFile(path,name);setMessage(done)}
    catch(e){setMessage(e instanceof Error?e.message:'내려받기 실패')}
    finally{setBusy(false)}
  }
  async function create(event:React.FormEvent){event.preventDefault();await act(async()=>{
    const job = await request<Job>('/jobs',{method:'POST',body:JSON.stringify({source_asset_id:asset,target_language:target,
      workflow:{audio_mode:audio,burn_subtitles:burn,source_language:sourceLanguage||null,voice_id:voice||null,lipsync:audio==='dub'&&lip,budget_usd:budget,
        ...(useClip&&draft ? {clip:{start:draft.start,end:draft.end,mode:draft.mode,focus_x:draft.focus_x,title:draft.title},transcript:draft.cues} : {})}})})
    setSelected(job.id);setUrl('');setPlayed(false);setMessage('작업을 시작했습니다. 단계별 결과가 아래에 표시됩니다.')
  })}
  function choose(id:string){setSelected(id);setDetail(null);setTranslated([]);setUrl('');setPlayed(false)}
  return <section className="clip-editor">
    <h2>단계별 영상 제작·게시</h2>
    <p>음성 인식·대본 확인 → 자막 번역 → 선택적 더빙 → 최종 검수 → 승인 후 예약</p>
    {config && <p>유료 처리 {config.paid_enabled?'켜짐':'꺼짐'} · 번역({config.translation_provider}{config.translation_refine_enabled?'+보정':''}) {config.translation_configured?'준비됨':'설정 필요'} · 더빙 {config.speech_configured?'준비됨':'설정 필요'} · YouTube {config.youtube_configured?'준비됨':'설정 필요'}</p>}
    <form onSubmit={create} className="editor-fields">
      <label>원본<select value={asset} onChange={e=>{setAsset(e.target.value);setUseClip(false)}} required><option value="">선택</option>{assets.filter(a=>a.upload_state==='verified').map(a=><option key={a.id} value={a.id}>{a.original_filename}</option>)}</select></label>
      <label>제작 방식<select value={audio} onChange={e=>setAudio(e.target.value)}><option value="original">원어 유지·자막 합성</option><option value="subtitles">자막만 번역 · 원음 유지</option><option value="dub">번역·더빙</option></select></label>
      <label>자막 표시<select value={burn?'burn':'track'} onChange={e=>setBurn(e.target.value==='burn')}><option value="burn">영상에 굽기 · 트랙 업로드 안 함</option><option value="track">YouTube 트랙만 · 영상에 굽지 않음</option></select></label>
      <label>원본 언어<select value={sourceLanguage} onChange={e=>setSourceLanguage(e.target.value)} required={!burn&&audio==='original'}><option value="">자동 감지</option>{sourceOptions.map(l=><option key={l.code} value={l.code}>{l.label}</option>)}</select></label>
      {audio!=='original' && <label>자막 번역 언어<select value={target} onChange={e=>setTarget(e.target.value)} required>{targetOptions.map(l=><option key={l.code} value={l.code}>{l.label}{l.tier>1?' (한국어에서만)':''}</option>)}</select></label>}
      {audio==='subtitles' && <p>원래 음성과 자막 시간을 유지합니다. 번역 결과는 검수 후 수정하거나 SRT·VTT로 내려받을 수 있습니다.</p>}
      {audio!=='original' && <label>작업 예산 상한 (USD)<input type="number" min="0" max="1" step="0.0001" value={budget} onChange={e=>setBudget(e.target.value)} required /></label>}
      {audio==='dub' && <><label>더빙 음성 ID<input value={voice} onChange={e=>setVoice(e.target.value)} required /></label>
        <label><input type="checkbox" checked={lip} onChange={e=>setLip(e.target.checked)} /> 립싱크 사용</label>
        <p>더빙 경로는 원래 대사와 배경음을 새 음성으로 교체합니다.</p></>}
      {draft&&draft.source_asset_id===asset && <label><input type="checkbox" checked={useClip} onChange={e=>setUseClip(e.target.checked)} /> 편집기에서 고른 {draft.start}~{draft.end}초를 숏폼으로 제작</label>}
      <button disabled={busy} type="submit">단계별 제작 시작</button>
    </form>
    <details><summary>이번 달 유료 처리 예산</summary><p>작업별 예산과 공통 월 예산을 함께 확인합니다. 사용한 금액과 아직 결과를 확인하지 못한 요청의 예약 금액도 포함합니다.</p>
      <label>월 상한 (USD)<input type="number" min="0.0001" step="0.0001" value={monthly} onChange={e=>setMonthly(e.target.value)} /></label>
      <button disabled={busy||!monthly} onClick={()=>void act(async()=>{await request('/workflow/monthly-budget',{method:'PUT',body:JSON.stringify({limit_usd:monthly})});setMessage('이번 달 공통 예산을 저장했습니다.')})}>월 예산 저장</button>
    </details>
    <label>진행 작업<select value={selected} onChange={e=>choose(e.target.value)}><option value="">선택</option>{jobs.map(j=><option key={j.id} value={j.id}>{label(j.target_language)} · {j.state} · {j.id.slice(0,8)}</option>)}</select></label>
    {detail && <>
      <p>{detail.state} · {detail.stage} {detail.reason}</p>
      <ol>{detail.stages.map(s=><li key={s.id}>{s.name} · {s.state} · 시도 {s.attempt}{s.estimated_cost&&` · 비용 상한 $${s.estimated_cost}`}
        {s.uncertain && <details><summary>공급자 내역 확인 후 처리</summary><p>요청 결과를 확인할 수 없어 자동 재호출을 막았습니다. 공급자의 실행·청구 내역을 확인한 경우에만 선택하세요.</p>
          {(['confirmed_no_charge','charged_without_result'] as const).map(outcome=><button key={outcome} disabled={busy} onClick={()=>{
            const note=window.prompt('공급자에서 확인한 내역을 적어주세요 (5자 이상).')
            if(!note)return
            void act(async()=>{await request(`/jobs/${detail.id}/stages/${s.id}/resolve`,{method:'POST',body:JSON.stringify({outcome,note})});setMessage('정산했습니다. 작업 재개로 다시 실행할 수 있습니다.')})
          }}>{outcome==='confirmed_no_charge'?'미청구 확인·예약 해제':'청구 확인·상한 정산'}</button>)}
        </details>}
      </li>)}</ol>
      {(detail.state==='blocked'||detail.state==='failed'||detail.state==='processing') && <>
        <button disabled={busy} onClick={()=>void act(async()=>{await request(`/jobs/${detail.id}/resume`,{method:'POST'})})}>설정 확인 후 작업 재개</button>
        <button disabled={busy} onClick={()=>{const amount=window.prompt('새 작업 예산 상한 (USD)');if(amount)void act(async()=>{await request(`/jobs/${detail.id}/budget`,{method:'PUT',body:JSON.stringify({limit_usd:amount})})})}}>작업 예산 수정</button>
      </>}
      {detail.cues.length>0 && (['srt','vtt'] as const).map(fmt=><button key={fmt} disabled={busy} onClick={()=>void grab(
        `/jobs/${detail.id}/subtitles?format=${fmt}`, `job-${detail.id}.${fmt}`,
        `자막 ${fmt.toUpperCase()} 파일을 내려받았습니다. 시각은 출력 영상 시작이 0초입니다.`,
      )}>자막 {fmt.toUpperCase()} 내려받기</button>)}
      {(detail.style_warnings?.length??0)>0 && <aside role="note" aria-label="문체 검수 안내">
        <strong>문체 혼용 확인 · 원문 말투 유지</strong>
        <p>문장은 자동으로 고치지 않습니다. 원문과 비교해 의도된 차이인지 확인해 주세요.</p>
        {detail.style_warnings?.map(w=><div key={w.kind}><p>{w.message}</p><ul>{w.registers.map(r=><li key={r.label}>{r.label}: 자막 {r.cue_numbers.join(', ')}번</li>)}</ul></div>)}
      </aside>}
      {(detail.translation_qa?.length??0)>0 && <aside role="note" aria-label="번역 검수 안내">
        <strong>번역 QA · 자동으로 고치지 않습니다</strong>
        <ul>{detail.translation_qa?.map(q=><li key={q.index}>자막 {q.index+1}번: {q.issues.join(' / ')}</li>)}</ul>
      </aside>}
      {detail.translated.length>0 && <details><summary>번역 검수·새 버전 만들기</summary>
        <button onClick={()=>setTranslated(detail.translated)}>번역 불러오기</button>
        {translated.map((c,i)=><label key={i}>자막 {i+1} · {c.start.toFixed(1)}~{c.end.toFixed(1)}초<textarea value={c.text} onChange={e=>setTranslated(rows=>rows.map((r,j)=>j===i?{...r,text:e.target.value}:r))} /></label>)}
        <button disabled={busy||translated.length!==detail.cues.length} onClick={()=>void act(async()=>{
          const job=jobs.find(j=>j.id===detail.id);if(!job)throw new Error('작업을 다시 조회하세요.')
          const result=await request<Job>('/jobs',{method:'POST',body:JSON.stringify({source_asset_id:job.source_asset_id,target_language:job.target_language,
            workflow:{...detail.options,reuse_from_job_id:detail.id,translated_cues:translated,transcript:detail.cues.map(c=>{const start=(detail.options.clip as {start:number}|null)?.start??0;return {...c,start:c.start+start,end:c.end+start}})}})})
          choose(result.id);setMessage('수정한 번역으로 새 작업을 만들었습니다. 새 결과물은 다시 승인해야 합니다.')
        })}>{detail.options.audio_mode==='dub'?'수정 문장으로 더빙·새 버전 제작':'수정 자막으로 새 버전 제작'}</button>
      </details>}
      {detail.artifact_id && <>
        <button disabled={busy} onClick={()=>void act(async()=>{const p=await request<{url:string}>(`/artifacts/${detail.artifact_id}/preview`);setUrl(p.url);setPlayed(false)})}>최종 영상 검수</button>
        {url&&<video src={url} controls onPlay={()=>setPlayed(true)} />}
        {!detail.approval_id && <button disabled={busy||!played} onClick={()=>void act(async()=>{await request(`/artifacts/${detail.artifact_id}/approve`,{method:'POST'})})}>이 결과물 승인</button>}
        {detail.approval_id&&<PublicationForm artifactId={detail.artifact_id} />}
      </>}
    </>}
    {message&&<p role="status">{message}</p>}
    <h3>게시 진행</h3><ul>{publications.map(p=><li key={p.id}>{p.title} · {p.state} · {new Date(p.publish_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} (한국 시간) {p.error}
      {p.video_id&&<a href={`https://www.youtube.com/watch?v=${encodeURIComponent(p.video_id)}`} target="_blank" rel="noreferrer">YouTube 확인</a>}
      {p.state==='failed'&&<button disabled={busy} onClick={()=>void act(async()=>{await request(`/publications/${p.id}/resume`,{method:'POST'})})}>기존 업로드 이어서 확인</button>}
      {p.state==='failed'&&<button disabled={busy} onClick={()=>{const value=window.prompt('새 예약 시각 (한국 시간, 예: 2026-12-31T18:00)');if(value)void act(async()=>{await request(`/publications/${p.id}/reschedule`,{method:'POST',body:JSON.stringify({publish_at:`${value}:00+09:00`})})})}}>예약 시각 수정</button>}
    </li>)}</ul>
  </section>
}
