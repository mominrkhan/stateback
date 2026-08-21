import type { ActionKey, CommandAttempt } from "../../api/types";

export interface ConfirmedBinding {
  operationId: string;
  actionKey: ActionKey;
  expectedVersion: number;
  approvalId?: string;
  normalizedReason: string;
}

export type IdentifierFactory = () => string;

export class CommandAttemptRegistry {
  readonly #attempts = new Map<string, Readonly<CommandAttempt>>();

  get(operationId: string): Readonly<CommandAttempt> | undefined { return this.#attempts.get(operationId); }

  confirm(binding: ConfirmedBinding, makeId: IdentifierFactory): Readonly<CommandAttempt> {
    if (this.#attempts.has(binding.operationId)) throw new Error("An unresolved command attempt already exists for this operation");
    const attempt = Object.freeze<CommandAttempt>({
      operationId: binding.operationId,
      actionKey: binding.actionKey,
      expectedVersion: binding.expectedVersion,
      ...(binding.approvalId === undefined ? {} : { approvalId: binding.approvalId }),
      reason: binding.normalizedReason,
      idempotencyKey: makeId(),
      correlationId: makeId(),
    });
    this.#attempts.set(binding.operationId, attempt);
    return attempt;
  }

  resolve(operationId: string): void { this.#attempts.delete(operationId); }
  abandon(operationId: string, ambiguityAcknowledged: boolean): void {
    if (!ambiguityAcknowledged) throw new Error("Abandonment requires ambiguity acknowledgement");
    this.#attempts.delete(operationId);
  }
  clear(): void { this.#attempts.clear(); }
}

export const sessionCommandAttempts = new CommandAttemptRegistry();
