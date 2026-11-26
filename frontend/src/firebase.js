import { apiGet } from "./api.js";

const firebaseConfig = {
  apiKey: (import.meta.env.VITE_FIREBASE_API_KEY || "").trim(),
  authDomain: (import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "").trim(),
  projectId: (import.meta.env.VITE_FIREBASE_PROJECT_ID || "").trim(),
  storageBucket: (import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "").trim(),
  messagingSenderId: (import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "").trim(),
  appId: (import.meta.env.VITE_FIREBASE_APP_ID || "").trim(),
};

/**
 * Return Firebase public web config from frontend VITE_FIREBASE_* env vars
 * when provided, or fall back to backend GET /api/config.
 */
export async function getFirebaseConfig() {
  if (firebaseConfig.apiKey && firebaseConfig.projectId) {
    return firebaseConfig;
  }
  return apiGet("config");
}

export default firebaseConfig;
