import { useId } from "react";

const APPROVAL_ACTIONS = new Set(["approve", "reject"]);

export interface ReasonValidation {
  normalized: string;
  maxLength: 200 | 500;
  error: string | null;
}

export function validateOperatorReason(actionKey: string, value: string): ReasonValidation {
  const normalized = value.trim();
  const maxLength = APPROVAL_ACTIONS.has(actionKey) ? 500 : 200;
  let error: string | null = null;
  if (normalized.length === 0) error = "Enter a reason.";
  else if (!/^[\x20-\x7e]+$/.test(normalized)) error = "Use ASCII characters only.";
  else if (normalized.length > maxLength) error = `Reason must be ${maxLength} characters or fewer.`;
  return { normalized, maxLength, error };
}

export interface OperatorReasonFieldProps {
  actionKey: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  showValidation?: boolean;
}

export function OperatorReasonField({
  actionKey,
  value,
  onChange,
  disabled = false,
  showValidation = false,
}: OperatorReasonFieldProps) {
  const fieldId = useId();
  const helpId = useId();
  const errorId = useId();
  const validation = validateOperatorReason(actionKey, value);
  const describedBy = showValidation && validation.error ? `${helpId} ${errorId}` : helpId;

  return (
    <div className="operator-reason-field">
      <label htmlFor={fieldId}>Operator reason</label>
      <textarea
        id={fieldId}
        value={value}
        disabled={disabled}
        aria-invalid={showValidation && validation.error ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
      <div id={helpId} className="operator-reason-field__meta">
        <span>Required; ASCII only. Leading and trailing whitespace is removed at confirmation.</span>
        <span>{value.trim().length}/{validation.maxLength}</span>
      </div>
      {showValidation && validation.error && (
        <span id={errorId} className="operator-reason-field__error">{validation.error}</span>
      )}
    </div>
  );
}
