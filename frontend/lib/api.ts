export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  'http://localhost:8000/api/v1';
export const WS_URL = API_BASE.replace(/^http/, 'ws') + '/live';
