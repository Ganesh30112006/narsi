/** A key for scanning from other systems. The key itself is only ever returned when it's created. */
export interface ApiKey {
  id: string;
  name: string;
  /** First characters of the key ("gpk_Ab12C3"), so keys can be told apart. */
  prefix: string;
  createdAt: string;
  lastUsedAt: string | null;
}

export interface CreatedApiKey extends ApiKey {
  key: string;
}
