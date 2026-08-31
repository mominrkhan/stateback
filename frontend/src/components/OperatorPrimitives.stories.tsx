import type { Meta, StoryObj } from "@storybook/react-vite";
import { AlertDialog } from "@base-ui/react/alert-dialog";
import { within, userEvent } from "storybook/test";
import { useState } from "react";

import { ConfirmationDialog } from "./ConfirmationDialog";
import { DefensiveState } from "./DefensiveState";
import { Skeleton } from "./Skeleton";
import { StateBadge } from "./StateBadge";

function Gallery() {
  const [open, setOpen] = useState(false);
  return <div style={{ display: "grid", gap: 24, width: "min(760px, 90vw)" }}><section><p className="eyebrow">CANONICAL STATES</p><div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{["SUCCEEDED", "UNKNOWN", "VERIFYING", "FAILED", "MANUAL_INTERVENTION"].map((state) => <StateBadge key={state} state={state} />)}</div></section><section><p className="eyebrow">CONTROLS</p><div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}><button className="primitive-button primitive-button--primary">Primary action</button><button className="primitive-button">Secondary</button><button className="primitive-button" disabled>Disabled</button><button className="primitive-button primitive-button--danger" onClick={() => setOpen(true)}>Open dialog</button></div></section><Skeleton variant="cards" label="Loading operator cards" /><DefensiveState kind="empty" title="Nothing waiting for approval"><p>The queue is clear.</p></DefensiveState><ConfirmationDialog open={open} title="Confirm verification" description="Verification gathers evidence and may remain inconclusive." confirmLabel="Request verification" onCancel={() => setOpen(false)} onConfirm={() => setOpen(false)}><p>This does not authorize a blind retry.</p></ConfirmationDialog></div>;
}

function OpenConfirmation() {
  const [open, setOpen] = useState(true);
  return <ConfirmationDialog open={open} title="Confirm verification" description="Verification may remain inconclusive." confirmLabel="Request verification" onCancel={() => setOpen(false)} onConfirm={() => setOpen(false)}><p>This does not authorize a blind retry.</p></ConfirmationDialog>;
}

function OpenAlert() {
  return <AlertDialog.Root defaultOpen><AlertDialog.Portal><AlertDialog.Backdrop className="confirmation-dialog__backdrop" /><AlertDialog.Viewport className="confirmation-dialog__viewport"><AlertDialog.Popup className="confirmation-dialog"><header className="confirmation-dialog__header"><div><AlertDialog.Title>Reject protected action?</AlertDialog.Title><AlertDialog.Description>This durable decision cannot be treated as provider execution.</AlertDialog.Description></div></header><div className="confirmation-dialog__actions"><AlertDialog.Close className="primitive-button">Cancel</AlertDialog.Close><AlertDialog.Close className="primitive-button primitive-button--danger">Reject action</AlertDialog.Close></div></AlertDialog.Popup></AlertDialog.Viewport></AlertDialog.Portal></AlertDialog.Root>;
}

const meta = { title: "Stateback/Operator primitives", component: Gallery } satisfies Meta<typeof Gallery>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const Narrow: Story = { parameters: { viewport: { defaultViewport: "mobile1" } } };
export const BadgesUnknownFailedVerifying: Story = { render: () => <div style={{ display: "flex", gap: 8 }}><StateBadge state="UNKNOWN" /><StateBadge state="FAILED" /><StateBadge state="VERIFYING" /></div> };
export const ButtonDefault: Story = { render: () => <button className="primitive-button primitive-button--primary">Approve action</button> };
export const ButtonHover: Story = { render: () => <button className="primitive-button">Hover target</button>, play: async ({ canvasElement }) => { await userEvent.hover(within(canvasElement).getByRole("button")); } };
export const ButtonDisabled: Story = { render: () => <button className="primitive-button" disabled>Unavailable</button> };
export const ButtonLoading: Story = { render: () => <button className="primitive-button" disabled aria-busy="true">Submitting…</button> };
export const DialogOpen: Story = { render: () => <OpenConfirmation /> };
export const AlertDialogOpen: Story = { render: () => <OpenAlert /> };
export const SkeletonLoading: Story = { render: () => <Skeleton variant="table" label="Loading operations" /> };
export const DefensiveEmpty: Story = { render: () => <DefensiveState kind="empty" title="No operations"><p>Submit a protected action to begin.</p></DefensiveState> };
