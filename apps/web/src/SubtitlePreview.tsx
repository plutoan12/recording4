import { useEffect, useRef, useState } from 'react'
import JASSUB from 'jassub'
import workerUrl from 'jassub/dist/worker/worker.js?worker&url'
import wasmUrl from 'jassub/dist/wasm/jassub-worker.wasm?url'
import modernWasmUrl from 'jassub/dist/wasm/jassub-worker-modern.wasm?url'
import { fetchBinary, request } from './api'

// 워커가 굽는 것과 같은 ASS를 API에서 받아 libass WASM(jassub)으로 그립니다. CSS 근사가
// 아니라 실제 렌더라 움직임·그라데이션·컬러 이모지가 영상과 같게 보입니다. 글꼴은
// /subtitle-fonts에서 받아 렌더러에 넣고, 한 번 받은 글꼴은 화면이 살아 있는 동안 다시 쓰지
// 않습니다. WASM이나 글꼴을 못 받으면 상태만 알리고 CSS 미리보기가 남습니다.

type PreviewResponse = { ass: string; seconds: number; width: number; height: number; fonts: string[] }

const fontCache = new Map<string, Promise<Uint8Array | null>>()

function loadFont(family: string): Promise<Uint8Array | null> {
  let pending = fontCache.get(family)
  if (!pending) {
    pending = fetchBinary(`/subtitle-fonts/${encodeURIComponent(family)}`).catch(() => null)
    fontCache.set(family, pending)
  }
  return pending
}

export function SubtitlePreview({ template, animation, preset, pacing, text, seconds = 3, stickers = [] }: { template: string; animation?: string; preset?: string; pacing?: string; text?: string; seconds?: number; stickers?: unknown[] }) {
  const stickersKey = JSON.stringify(stickers)
  // 아래 useEffect 와 **같은 값들**로 만듭니다. JASSUB 은 생성자에서 캔버스를
  // transferControlToOffscreen() 으로 넘기고 destroy() 에서 DOM 에서 떼어 냅니다.
  // 한 캔버스는 한 번만 넘길 수 있어(실측: InvalidStateError), 같은 <canvas> 를
  // 다시 쓰면 설정을 한 번 바꾼 뒤부터 미리보기가 영영 "쓸 수 없음"이 됩니다.
  // key 를 바꿔 React 가 새 캔버스를 만들게 합니다.
  const canvasKey = JSON.stringify([template, animation, preset, pacing, text, seconds, stickersKey])
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [note, setNote] = useState('')

  useEffect(() => {
    let cancelled = false
    let instance: JASSUB | null = null
    let frame = 0
    setStatus('loading'); setNote('')
    void (async () => {
      try {
        const preview = await request<PreviewResponse>('/subtitle-preview', {
          method: 'POST',
          // 템플릿 글자 크기는 1080x1920 기준이라 그 크기로 만들고, 캔버스는 작게 그립니다(libass가 비율을 맞춥니다).
          body: JSON.stringify({ template, animation: animation || null, preset: preset || null, pacing: pacing || null, text: text || null, width: 1080, height: 1920, seconds, stickers }),
        })
        const loaded = await Promise.all(preview.fonts.map(async family => [family, await loadFont(family)] as const))
        if (cancelled || !canvasRef.current) return
        const missing = loaded.filter(([, bytes]) => !bytes).map(([family]) => family)
        const fonts = loaded.flatMap(([, bytes]) => (bytes ? [bytes] : []))
        const canvas = canvasRef.current
        canvas.width = preview.width / 2
        canvas.height = preview.height / 2
        instance = new JASSUB({ canvas, subContent: preview.ass, fonts, workerUrl, wasmUrl, modernWasmUrl, queryFonts: false })
        await instance.ready
        if (cancelled) { void instance.destroy(); return }
        setStatus('ready')
        setNote(missing.length ? `글꼴을 받지 못해 다른 글꼴로 그립니다: ${missing.join(', ')}` : '')
        const started = performance.now()
        // 움직임을 줄여 달라고 한 사람에게는 한 장만 그립니다. styles.css 의 규칙은
        // .template-preview span 에만 걸려 이 캔버스에는 닿지 않습니다.
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          void instance.manualRender({ expectedDisplayTime: started, width: preview.width / 2, height: preview.height / 2, mediaTime: preview.seconds / 2 })
          return
        }
        const tick = () => {
          const now = performance.now()
          const mediaTime = ((now - started) / 1000) % preview.seconds
          void instance?.manualRender({ expectedDisplayTime: now, width: preview.width / 2, height: preview.height / 2, mediaTime })
          frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
      } catch (error) {
        if (cancelled) return
        setStatus('unavailable')
        setNote(error instanceof Error ? error.message : '미리보기를 만들지 못했습니다.')
      }
    })()
    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
      if (instance) void instance.destroy()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, animation, preset, pacing, text, seconds, stickersKey])

  return <div className="subtitle-preview">
    {status !== 'unavailable' && <canvas key={canvasKey} ref={canvasRef} aria-label="자막 정확 미리보기" />}
    <small>{status === 'loading' ? '정확 미리보기(libass)를 준비하는 중…' : status === 'ready' ? `정확 미리보기(libass). ${seconds}초 반복 재생. ${note}` : `정확 미리보기를 쓸 수 없습니다: ${note}`}</small>
  </div>
}
