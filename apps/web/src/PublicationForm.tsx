import { useState } from 'react'
import { request } from './api'

export function PublicationForm({ artifactId }: { artifactId: string }) {
  const [title,setTitle] = useState('')
  const [description,setDescription] = useState('')
  const [when,setWhen] = useState('')
  const [kids,setKids] = useState('')
  const [busy,setBusy] = useState(false)
  const [message,setMessage] = useState('')
  async function submit(event: React.FormEvent) {
    event.preventDefault();setBusy(true);setMessage('')
    try {
      // The input is explicitly Korea time, independent of the browser's time zone.
      const publishAt = new Date(`${when}:00+09:00`).toISOString()
      await request('/publications',{method:'POST',body:JSON.stringify({artifact_id:artifactId,
        title,description,publish_at:publishAt,made_for_kids:kids==='yes'})})
      setMessage('예약 요청을 저장했습니다. 업로드·영상 처리 후 예약 결과를 확인합니다.')
    } catch(e) { setMessage(e instanceof Error ? e.message : '예약 요청 실패') }
    finally { setBusy(false) }
  }
  return <form className="publication-form" onSubmit={submit}>
    <h3>YouTube 공개 예약</h3>
    <p>승인한 영상 버전을 서버에 연결된 채널로 업로드합니다.</p>
    <label>게시 제목<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={100} required /></label>
    <label>설명<textarea value={description} onChange={e=>setDescription(e.target.value)} maxLength={5000} /></label>
    <label>공개 시각 (한국 시간)<input type="datetime-local" value={when} onChange={e=>setWhen(e.target.value)} required /></label>
    <label>아동용 콘텐츠<select value={kids} onChange={e=>setKids(e.target.value)} required>
      <option value="">선택</option><option value="yes">예</option><option value="no">아니요</option>
    </select></label>
    <button disabled={busy} type="submit">승인 영상 업로드·예약 요청</button>
    {message && <p role="status">{message}</p>}
  </form>
}
