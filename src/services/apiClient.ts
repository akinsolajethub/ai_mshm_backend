import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://ai-mshm-backend-d47t.onrender.com/api/v1';

// Note: NO trailing slash on baseURL. All endpoint paths start after /api/v1 (e.g. /auth/me/, /centers/phc/profile/)
const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

// Attach token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let failedQueue: Array<{ resolve: Function; reject: Function }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token);
  });
  failedQueue = [];
};

// Auto-refresh on 401
apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return apiClient.request(originalRequest);
          })
          .catch((queueError) => Promise.reject(queueError));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('refresh_token');

      if (!refreshToken) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.dispatchEvent(new CustomEvent('auth-expired'));
        window.location.href = '/login';
        isRefreshing = false;
        return Promise.reject(error);
      }

      try {
        const { data } = await axios.post(`${API_BASE_URL}/auth/token/refresh/`, {
          refresh: refreshToken,
        });

        const newAccess = data?.data?.access ?? data?.access;
        const newRefresh = data?.data?.refresh ?? data?.refresh;

        localStorage.setItem('access_token', newAccess);
        if (newRefresh) {
          localStorage.setItem('refresh_token', newRefresh);
        }

        apiClient.defaults.headers.common.Authorization = `Bearer ${newAccess}`;
        originalRequest.headers.Authorization = `Bearer ${newAccess}`;

        processQueue(null, newAccess);
        return apiClient.request(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.dispatchEvent(new CustomEvent('auth-expired'));
        window.dispatchEvent(
          new CustomEvent('show-toast', {
            detail: {
              message: 'Your session has expired. Please sign in again.',
              type: 'warning',
            },
          })
        );

        const currentPath = window.location.pathname;
        if (currentPath.startsWith('/clinician')) {
          window.location.href = '/clinician/login';
        } else if (currentPath.startsWith('/fmc')) {
          window.location.href = '/fmc/login';
        } else if (currentPath.startsWith('/phc')) {
          window.location.href = '/phc/login';
        } else {
          window.location.href = '/login';
        }

        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default apiClient;
