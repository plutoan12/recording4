// 관리 API 호출. 토큰은 메모리와 sessionStorage에만 두고 저장소·YouTube 자격증명은 다루지 않습니다.

const BASE = '/api'
const TOKEN_KEY = 'r4.access_token'

export type JobState =
  | 'queued'
  | 'processing'
  | 'blocked'
  | 'review_required'
  | 'approved'
  | 'rejected'
  | 'failed'
  | 'cancelled'

export interface SourceAsset {
  id: string
  original_filename: string
  storage_key: string
  upload_state: 'awaiting_upload' | 'uploaded' | 'verified' | 'rejected'
  byte_size: number | null
  duration_seconds: string | null
  width: number | null
  height: number | null
  probe_error: string | null
  created_at: string
}

export interface Job {
  id: string
  source_asset_id: string
  target_language: string
  state: JobState
  current_stage: string | null
  state_reason: string | null
  created_at: string
  updated_at: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token === null) sessionStorage.removeItem(TOKEN_KEY)
  else sessionStorage.setItem(TOKEN_KEY, token)
}

// 글꼴 파일처럼 JSON이 아닌 응답. 토큰은 같은 방식으로 붙입니다.
export async function fetchBinary(path: string): Promise<Uint8Array> {
  const token = getToken()
  const response = await fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!response.ok) throw new ApiError(response.status, `파일을 받지 못했습니다 (${response.status})`)
  return new Uint8Array(await response.arrayBuffer())
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined)
    throw new ApiError(response.status, (typeof detail === "string" ? detail : JSON.stringify(detail)) ?? `요청이 실패했습니다 (${response.status})`)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

function serverFilename(header: string | null): string | null {
  // 서버가 정한 이름을 씁니다(작업 자막은 언어가 붙습니다). 경로 조각은 버립니다.
  const name = header?.match(/filename="([^"]+)"/)?.[1]?.split(/[\\/]/).pop()
  return name && name !== '.' && name !== '..' ? name : null
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  // 자막 파일은 토큰이 필요해 <a href>로 바로 받을 수 없습니다. 받아서 저장만 합니다.
  const token = getToken()
  const response = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined)
    throw new ApiError(response.status, typeof detail === 'string' ? detail : `내려받기에 실패했습니다 (${response.status})`)
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = serverFilename(response.headers.get('Content-Disposition')) ?? filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export type EncodingChoice = { encoding: string; preview: string }
export type ImportResult =
  | { ok: true; version: number; count: number; skipped: string[];
      violations: {index:number;kind:string;detail:string}[];
      // encoding_detected가 true면 판별기가 고른 것이라 글자가 깨졌을 수 있습니다.
      // choices는 그때 함께 오는 다른 후보입니다.
      encoding: string; encoding_detected: boolean; choices?: EncodingChoice[] }
  | { ok: false; message: string; choices: EncodingChoice[] }

export async function importSubtitles(
  assetId: string,
  file: File,
  encoding?: string,
): Promise<ImportResult> {
  // 파일은 바이트 그대로 보냅니다. 브라우저가 글자로 먼저 바꾸면 UTF-8이 아닌
  // 파일(한국어 자막에 흔한 CP949)이 그 자리에서 깨집니다.
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  const token = getToken()
  const response = await fetch(`${BASE}/source-assets/${assetId}/transcript/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content_base64: btoa(binary), ...(encoding ? { encoding } : {}) }),
  })
  const body = await response.json().catch(() => undefined)
  if (response.ok) return { ok: true, ...body }
  const detail = body?.detail
  // 인코딩을 고르라는 응답은 실패가 아니라 다음 단계입니다.
  if (detail && typeof detail === 'object' && Array.isArray(detail.choices)) {
    return { ok: false, message: detail.message, choices: detail.choices }
  }
  throw new ApiError(response.status, typeof detail === 'string' ? detail : `자막을 들이지 못했습니다 (${response.status})`)
}

export async function login(email: string, password: string): Promise<void> {
  const body = await request<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(body.access_token)
}

export const listAssets = () => request<SourceAsset[]>('/source-assets')
export const listJobs = () => request<Job[]>('/jobs')

export async function uploadSource(file: File): Promise<SourceAsset> {
  // 1. API가 권한을 확인하고 서명 URL을 발급합니다.
  const created = await request<{
    source_asset_id: string
    upload_url: string
  }>('/source-assets', {
    method: 'POST',
    body: JSON.stringify({ filename: file.name, byte_size: file.size }),
  })

  // 2. 브라우저가 저장소로 직접 올립니다. 이 요청에는 API 토큰을 붙이지 않습니다.
  const uploaded = await fetch(created.upload_url, { method: 'PUT', body: file })
  if (!uploaded.ok) throw new ApiError(uploaded.status, '저장소 업로드에 실패했습니다.')

  // 3. API가 파일 존재와 크기를 검증하고 워커 검사를 요청합니다.
  return request<SourceAsset>(`/source-assets/${created.source_asset_id}/complete`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export const createJob = (sourceAssetId: string, targetLanguage: string) =>
  request<Job>('/jobs', {
    method: 'POST',
    body: JSON.stringify({ source_asset_id: sourceAssetId, target_language: targetLanguage }),
  })

export const importSourceLink = (url: string) => request<SourceAsset>('/source-assets/import-link', {
  method: 'POST', body: JSON.stringify({url}),
})
