import { useEffect, useRef, useState } from 'react'
import { request } from './api'

type Template = {id:string; name:string; description:string}
type Preview = {ass:string; duration:number; width:number; height:number}

function CaptionPreview({template}:{template:string}) {
  const host = useRef<HTMLDivElement>(null)
  const [error,setError] = useState('')
  useEffect(()=>{
    let cancelled=false
    let timer:ReturnType<typeof setTimeout>|undefined
    let renderer:import('jassub').default|undefined
    const canvas=document.createElement('canvas')
    canvas.width=270;canvas.height=480
    canvas.style.cssText='width:100%;height:100%;display:block'
    host.current?.replaceChildren(canvas)
    setError('')
    async function start(){
      try {
        const [preview, {default:JASSUB},fontResponse]=await Promise.all([
          request<Preview>('/subtitle-templates/preview',{method:'POST',body:JSON.stringify({template})}),
          import('jassub'),fetch('/fonts/NotoSansCJKkr-Regular.otf'),
        ])
        if(!fontResponse.ok)throw new Error('한국어 글꼴을 불러오지 못했습니다.')
        const font=new Uint8Array(await fontResponse.arrayBuffer())
        if(cancelled)return
        renderer=new JASSUB({canvas,subContent:preview.ass,fonts:[font],
          defaultFont:'Noto Sans CJK KR',queryFonts:false})
        await renderer.ready
        const started=performance.now()
        async function frame(){
          if(cancelled||!renderer)return
          try {
            await renderer.manualRender({expectedDisplayTime:performance.now(),width:270,height:480,
              mediaTime:((performance.now()-started)/1000)%preview.duration})
            if(!cancelled)timer=setTimeout(()=>void frame(),1000/24)
          }catch(cause){if(!cancelled)setError(cause instanceof Error?cause.message:'미리보기 실패')}
        }
        if(!cancelled)void frame()
      }catch(cause){if(!cancelled)setError(cause instanceof Error?cause.message:'이 브라우저에서 미리보기를 실행하지 못했습니다.')}
    }
    void start()
    return ()=>{cancelled=true;if(timer)clearTimeout(timer);if(renderer)void renderer.destroy().catch(()=>{});canvas.remove()}
  },[template])
  return <div>
    <p>스타일 미리보기 · 예시 문장 · 실제 결과물은 제작 후 검수하세요.</p>
    <div ref={host} role="img" aria-label="선택한 자막 템플릿의 한국어 예시"
      style={{width:270,height:480,background:'linear-gradient(160deg,#22384c,#111827)',borderRadius:12}} />
    {error&&<p role="alert">{error} 최종 영상은 서버 렌더링으로 확인할 수 있습니다.</p>}
  </div>
}

export function SubtitleTemplatePicker({value,onChange}:{value:string;onChange:(value:string)=>void}) {
  const [templates,setTemplates]=useState<Template[]>([])
  const [show,setShow]=useState(false)
  const [error,setError]=useState('')
  useEffect(()=>{let active=true;void request<Template[]>('/subtitle-templates').then(data=>{
    if(active)setTemplates(data)
  }).catch(()=>{if(active)setError('자막 템플릿 목록을 불러오지 못했습니다.')});return()=>{active=false}},[])
  return <fieldset style={{gridColumn:'1 / -1',minWidth:0}}>
    <legend>자막 템플릿</legend>
    <label>스타일 <select value={value} onChange={e=>onChange(e.target.value)}>
      {templates.length===0&&<option value="classic">기본 번역형</option>}
      {templates.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}
    </select></label>
    <p>{templates.find(t=>t.id===value)?.description}</p>
    {error&&<p role="alert">{error}</p>}
    <button type="button" onClick={()=>setShow(s=>!s)}>{show?'미리보기 닫기':'스타일 미리보기'}</button>
    {show&&<CaptionPreview template={value} />}
  </fieldset>
}
