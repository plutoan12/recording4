export type MosaicRegion = {
  start: number; end: number; x: number; y: number; width: number; height: number; block_size: number
}

export function mosaicRegionIssue(regions: MosaicRegion[], seconds: number): string {
  if (regions.length > 20) return '모자이크 영역은 최대 20개입니다.'
  for (const [i, r] of regions.entries()) {
    if (!Object.values(r).every(Number.isFinite) || r.start < 0 || r.end <= r.start || r.end > seconds)
      return `${i + 1}번 모자이크의 시작·종료를 결과 영상 길이 안에서 정해 주세요.`
    if (r.x < 0 || r.y < 0 || r.width <= 0 || r.height <= 0 || r.x + r.width > 1 + 1e-9 || r.y + r.height > 1 + 1e-9)
      return `${i + 1}번 모자이크 영역이 화면 밖이거나 크기가 없습니다.`
    if (!Number.isInteger(r.block_size) || r.block_size < 4 || r.block_size > 100)
      return `${i + 1}번 모자이크 크기는 4~100의 정수로 정해 주세요.`
  }
  return ''
}

export function MosaicRegionEditor({ regions, seconds, busy, onChange }: {
  regions: MosaicRegion[]; seconds: number; busy: boolean; onChange: (regions: MosaicRegion[]) => void
}) {
  const issue = mosaicRegionIssue(regions, seconds)
  function update(index: number, key: keyof MosaicRegion, value: number) {
    onChange(regions.map((r, i) => i === index ? { ...r, [key]: value } : r))
  }
  return <details>
    <summary>구간 모자이크 보완 ({regions.length}개)</summary>
    <p>자동 감지에서 빠진 얼굴이나 가리고 싶은 곳을 사각형으로 지정하세요. 자동 얼굴 모자이크와 함께 쓰거나 단독으로 쓸 수 있습니다.</p>
    <p>시각은 구간을 이어 붙이고 배속을 적용한 <b>결과 영상의 0초</b>부터 셉니다. 위치와 크기는 검은 여백을 포함한 세로 화면 전체의 비율입니다. 구간·배속을 바꾸면 가릴 시각도 확인하세요.</p>
    <button type="button" disabled={busy || regions.length >= 20 || seconds <= 0} onClick={() => onChange([
      ...regions, { start: 0, end: Math.min(3, seconds), x: 0.25, y: 0.25, width: 0.5, height: 0.5, block_size: 30 },
    ])}>가릴 영역 추가</button>
    {regions.map((r, i) => <fieldset key={i} disabled={busy}>
      <legend>모자이크 영역 {i + 1}</legend>
      <div className="editor-fields">
        <label>가림 시작(초)<input type="number" min="0" step="0.01" value={r.start} onChange={e => update(i, 'start', Number(e.target.value))} /></label>
        <label>가림 종료(초)<input type="number" min="0" max={seconds} step="0.01" value={r.end} onChange={e => update(i, 'end', Number(e.target.value))} /></label>
        {([['x', '왼쪽 위치'], ['y', '위쪽 위치'], ['width', '너비'], ['height', '높이']] as const).map(([key, label]) =>
          <label key={key}>{label}(%)<input type="number" min="0" max="100" step="0.1" value={Number((r[key] * 100).toFixed(4))}
            onChange={e => update(i, key, Number(e.target.value) / 100)} /></label>)}
        <label>가림 모자이크 크기(px)<input type="number" min="4" max="100" step="1" value={r.block_size} onChange={e => update(i, 'block_size', Number(e.target.value))} /></label>
      </div>
      <button type="button" onClick={() => onChange(regions.filter((_, index) => index !== i))}>이 영역 삭제</button>
    </fieldset>)}
    {regions.length > 0 && <>
      <p>위치 도식입니다. 실제 영상은 아래의 한 장 미리보기와 최종 영상에서 확인하세요.</p>
      <div role="img" aria-label="완성 세로 화면의 모자이크 위치 도식" style={{ position: 'relative', width: 144, aspectRatio: '9 / 16', background: '#151820', border: '1px solid #8791a3', overflow: 'hidden' }}>
        {regions.map((r, i) => <div key={i} style={{ position: 'absolute', boxSizing: 'border-box', left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.width * 100}%`, height: `${r.height * 100}%`, background: '#7259cc66', border: '2px solid #d4c8ff', color: '#fff' }}>{i + 1}</div>)}
      </div>
      <p>지정 영역은 한 장 미리보기에도 반영됩니다. 자동 얼굴 감지 결과는 최종 영상에서 확인하세요. 원음은 유지합니다.</p>
    </>}
    {issue && <p role="alert" className="error">{issue}</p>}
  </details>
}
