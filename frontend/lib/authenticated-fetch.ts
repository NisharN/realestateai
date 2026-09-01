export interface AuthenticatedFetchOptions {
  baseUrl: string;
  getAccessToken: () => Promise<string | null>;
  getWorkspaceId: () => string | null;
  /**
   * When true, requests proceed without a session token. Used for demo
   * deployments where the backend authenticates everyone as a local demo
   * user (see backend DEMO_AUTH) so the product can be walked through with
   * no accounts and no keys.
   */
  allowAnonymous?: () => boolean;
}

export class AuthenticationRequiredError extends Error {
  constructor() {
    super("Authentication required");
    this.name = "AuthenticationRequiredError";
  }
}

export function createAuthenticatedFetch(options: AuthenticatedFetchOptions) {
  return async function authenticatedFetch(
    endpoint: string,
    init: RequestInit = {},
  ): Promise<Response> {
    const token = await options.getAccessToken();
    const workspaceId = options.getWorkspaceId();
    const anonymousAllowed = options.allowAnonymous?.() ?? false;

    if (!token && !anonymousAllowed) {
      throw new AuthenticationRequiredError();
    }

    const headers = Object.fromEntries(new Headers(init.headers).entries());
    if (token) headers.Authorization = `Bearer ${token}`;
    // Retained for backward compatibility with deployments that still route
    // through a shared instance. Single-tenant backends ignore it and read the
    // workspace from their own configuration instead.
    if (workspaceId) headers["X-Workspace-ID"] = workspaceId;

    return fetch(`${options.baseUrl}${endpoint}`, { ...init, headers });
  };
}
