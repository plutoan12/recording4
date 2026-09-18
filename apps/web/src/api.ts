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
