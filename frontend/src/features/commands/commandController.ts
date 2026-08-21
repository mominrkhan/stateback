import type { OperatorClient } from "../../api/client";
import { ApiError, ClientFailure } from "../../api/errors";
import type { ActionKey, CommandAttempt, Reconstruction } from "../../api/types";
import { validateOperatorReason } from "../../components/OperatorReasonField";
import { CommandAttemptRegistry, sessionCommandAttempts, type IdentifierFactory } from "./attemptRegistry";

export type CommandPhase = "idle" | "submitting" | "accepted-reloading" | "accepted" | "authoritative-reloaded" | "conflict" | "forbidden" | "validation-error" | "rate-limited" | "indeterminate" | "error";
export interface CommandState {
  phase: CommandPhase;
  operationId: string | null;
  reason: string;
  reconstruction: Reconstruction | null;
  retrySameRequest: boolean;
  controlsDisabled: boolean;
  message: string | null;
  readGeneration: number;
}
type Listener = (state: Readonly<CommandState>) => void;

const INITIAL: CommandState = { phase: "idle", operationId: null, reason: "", reconstruction: null, retrySameRequest: false, controlsDisabled: false, message: null, readGeneration: 0 };

export class CommandController {
  #state: CommandState = INITIAL;
  readonly #listeners = new Set<Listener>();
  readonly #client: OperatorClient;
  readonly #registry: CommandAttemptRegistry;
  readonly #makeId: IdentifierFactory;

  constructor(client: OperatorClient, options: { registry?: CommandAttemptRegistry; makeId?: IdentifierFactory } = {}) {
    this.#client = client; this.#registry = options.registry ?? sessionCommandAttempts; this.#makeId = options.makeId ?? (() => crypto.randomUUID());
  }
  get state(): Readonly<CommandState> { return this.#state; }
  subscribe(listener: Listener): () => void { this.#listeners.add(listener); return () => this.#listeners.delete(listener); }
  retained(operationId: string): Readonly<CommandAttempt> | undefined { return this.#registry.get(operationId); }

  async confirm(reconstruction: Reconstruction, actionKey: ActionKey, reasonInput: string, approvalId?: string): Promise<void> {
    if (!reconstruction.available_actions.includes(actionKey)) throw new Error("Action is not available in authoritative reconstruction");
    if ((actionKey === "approve" || actionKey === "reject") && !approvalId) throw new Error("Approval action requires the current approval ID");
    const validation = validateOperatorReason(actionKey, reasonInput); if (validation.error) throw new Error(validation.error);
    const attempt = this.#registry.confirm({ operationId: reconstruction.operation.operation_id, actionKey, expectedVersion: reconstruction.operation.version, approvalId, normalizedReason: validation.normalized }, this.#makeId);
    await this.#execute(attempt, reconstruction);
  }

  async retrySame(operationId: string): Promise<void> {
    const attempt = this.#registry.get(operationId); if (!attempt || !this.#state.retrySameRequest || !this.#state.reconstruction) throw new Error("No same-request retry is available");
    await this.#execute(attempt, this.#state.reconstruction);
  }

  abandon(operationId: string, ambiguityAcknowledged: boolean): void {
    this.#registry.abandon(operationId, ambiguityAcknowledged);
    this.#set({ ...INITIAL, operationId, reason: this.#state.reason, readGeneration: this.#state.readGeneration });
  }

  reviewNew(operationId: string, ambiguityAcknowledged: boolean): string {
    const reason = this.#state.reason; this.abandon(operationId, ambiguityAcknowledged); return reason;
  }

  async #execute(attempt: Readonly<CommandAttempt>, baseline: Reconstruction): Promise<void> {
    this.#set({ phase: "submitting", operationId: attempt.operationId, reason: attempt.reason, reconstruction: baseline, retrySameRequest: false, controlsDisabled: true, message: null, readGeneration: this.#state.readGeneration });
    try {
      await this.#client.command(attempt);
      this.#set({ ...this.#state, phase: "accepted-reloading", message: "Command accepted; reloading authoritative state." });
      const fresh = await this.#reload(attempt.operationId);
      if (fresh) { this.#registry.resolve(attempt.operationId); this.#set({ ...this.#state, phase: "accepted", reconstruction: fresh, controlsDisabled: false, message: "Authoritative reconstruction reloaded." }); }
    } catch (cause) {
      if (cause instanceof ApiError) await this.#apiFailure(cause, attempt, baseline);
      else if (cause instanceof ClientFailure && cause.indeterminate) await this.#indeterminate(cause.message, attempt, baseline);
      else await this.#indeterminate("Command transport result is unknown.", attempt, baseline);
    }
  }

  async #apiFailure(error: ApiError, attempt: Readonly<CommandAttempt>, baseline: Reconstruction): Promise<void> {
    if (error.status === 500 || error.status === 503) { await this.#indeterminate(error.message, attempt, baseline); return; }
    if (error.status === 409) {
      this.#registry.resolve(attempt.operationId); this.#set({ ...this.#state, phase: "conflict", controlsDisabled: true, message: error.message });
      const fresh = await this.#reload(attempt.operationId); if (fresh) this.#set({ ...this.#state, reconstruction: fresh, controlsDisabled: false }); return;
    }
    this.#registry.resolve(attempt.operationId);
    const phase: CommandPhase = error.status === 403 ? "forbidden" : error.status === 422 ? "validation-error" : error.status === 429 ? "rate-limited" : "error";
    this.#set({ ...this.#state, phase, controlsDisabled: false, message: error.message });
  }

  async #indeterminate(message: string, attempt: Readonly<CommandAttempt>, _baseline: Reconstruction): Promise<void> {
    this.#set({ ...this.#state, phase: "indeterminate", controlsDisabled: true, retrySameRequest: false, message });
    const fresh = await this.#reload(attempt.operationId);
    if (!fresh) return;
    const unchanged = fresh.operation.version === attempt.expectedVersion;
    const stillAvailable = fresh.available_actions.includes(attempt.actionKey);
    if (!unchanged || !stillAvailable) {
      this.#registry.resolve(attempt.operationId);
      this.#set({ ...this.#state, phase: "authoritative-reloaded", reconstruction: fresh, controlsDisabled: false, message: "Authoritative state or eligibility changed; the local retry was cleared without inferring command outcome." });
      return;
    }
    this.#set({ ...this.#state, reconstruction: fresh, retrySameRequest: true, controlsDisabled: true, message: `${message} Authoritative state is unchanged; only the identical request may be retried.` });
  }

  async #reload(operationId: string): Promise<Reconstruction | null> {
    const generation = this.#state.readGeneration + 1; this.#set({ ...this.#state, readGeneration: generation });
    try { const fresh = await this.#client.reconstruct(operationId); if (this.#state.readGeneration !== generation) return null; return fresh; }
    catch { if (this.#state.readGeneration === generation) this.#set({ ...this.#state, controlsDisabled: true, message: `${this.#state.message ?? "Command status unresolved"} Authoritative reload failed.` }); return null; }
  }

  #set(state: CommandState): void { this.#state = state; for (const listener of this.#listeners) listener(state); }
}
