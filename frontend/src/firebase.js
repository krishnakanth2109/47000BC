import { apiGet } from "./api.js";

/**
 * Firebase configuration is managed on the backend via FIREBASE_* env vars
 * and exposed safely when needed via GET /api/config.
 */
export async function getFirebaseConfig() {
  return apiGet("config");
}
