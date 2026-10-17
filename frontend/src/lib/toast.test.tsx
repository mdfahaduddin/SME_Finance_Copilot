import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { errorText, toast, Toaster } from "./toast";

const shown: number[] = [];
const show = (fn: () => number) => act(() => { shown.push(fn()); });

describe("toasts", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    act(() => shown.splice(0).forEach((id) => toast.dismiss(id)));
    vi.useRealTimers();
  });

  it("shows a success message and removes it after 4 seconds", () => {
    render(<Toaster />);
    show(() => toast.success("Business profile saved", "All changes are live."));
    expect(screen.getByRole("status")).toHaveTextContent("Business profile saved");
    expect(screen.getByText("All changes are live.")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText("Business profile saved")).not.toBeInTheDocument();
  });

  it("announces errors as alerts and keeps them longer", () => {
    render(<Toaster />);
    show(() => toast.error("Download failed", "Network error"));
    expect(screen.getByRole("alert")).toHaveTextContent("Download failed");
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows at most four at a time, newest last", () => {
    render(<Toaster />);
    for (const n of [1, 2, 3, 4, 5]) show(() => toast.info(`Message ${n}`));
    expect(screen.getAllByRole("status")).toHaveLength(4);
    expect(screen.queryByText("Message 1")).not.toBeInTheDocument();
    expect(screen.getByText("Message 5")).toBeInTheDocument();
  });

  it("can be dismissed by hand", async () => {
    vi.useRealTimers();
    render(<Toaster />);
    show(() => toast.success("Conversation deleted"));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Conversation deleted")).not.toBeInTheDocument();
  });

  it("errorText reads the message of any thrown value", () => {
    expect(errorText(new Error("boom"))).toBe("boom");
    expect(errorText("plain")).toBe("plain");
  });
});
