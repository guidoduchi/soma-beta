export class OwnerRequestError extends Error {
  constructor(readonly code: string, readonly status: number) {super(code);}
}
/** Same-origin transport. Error bodies and draft-bearing requests are never logged. */
export async function ownerQuery<T>(path: string, signal: AbortSignal): Promise<T> {
  if (!path.startsWith('/api/v1/') || path.includes('\\') || path.includes('#') || path.includes('//')) throw new Error('Invalid owner route');
  const response = await fetch(path, {signal, credentials: 'same-origin', redirect: 'error', headers: {Accept: 'application/json'}});
  if (!response.ok) throw new OwnerRequestError(response.status === 401 ? 'AUTHENTICATION_REQUIRED' : 'OWNER_QUERY_FAILED', response.status);
  const length = response.headers.get('content-length');
  if (length !== null && Number(length) > 4 * 1024 * 1024) throw new Error('Owner projection exceeds transport bound');
  const reader = response.body?.getReader(); if (!reader) throw new Error('Owner projection is absent');
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const part = await reader.read(); if (part.done) break;
      size += part.value.length; if (size > 4 * 1024 * 1024) throw new Error('Owner projection exceeds transport bound');
      chunks.push(part.value);
    }
  } finally {await reader.cancel();}
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
  return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)) as T;
}
