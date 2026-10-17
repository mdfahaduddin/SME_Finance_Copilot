import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSession } from "../../lib/types";
import { ConversationList } from "./ConversationList";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api", () => ({ api }));

const today = new Date().toISOString();
const sessions: ChatSession[] = [
  { id: 3, title: "Oven purchase plan", createdAt: today, lastMessageAt: today, pinned: true },
  { id: 2, title: "Who owes me money?", createdAt: today, lastMessageAt: today, pinned: false },
  { id: 1, title: "Will I run out of cash?", createdAt: "2026-01-02T10:00:00Z", lastMessageAt: "2026-01-02T10:00:00Z", pinned: false },
];

function setup(overrides: Partial<Parameters<typeof ConversationList>[0]> = {}) {
  const props = {
    sessions, activeId: 2, onSelect: vi.fn(), onNew: vi.fn(),
    onPin: vi.fn(async () => {}), onRename: vi.fn(async () => {}), onDelete: vi.fn(async () => {}), ...overrides,
  };
  render(<ConversationList {...props} />);
  return props;
}

describe("conversation list", () => {
  beforeEach(() => api.mockReset());

  it("puts pinned conversations first, then groups by date", () => {
    setup();
    const labels = screen.getAllByText(/^(Pinned|Today|Older)$/).map((el) => el.textContent);
    expect(labels).toEqual(["Pinned", "Today", "Older"]);
    expect(screen.getByRole("button", { name: /Who owes me money\?/, current: true })).toBeInTheDocument();
  });

  it("opens a conversation and starts a new one", async () => {
    const props = setup();
    await userEvent.click(screen.getByText("Will I run out of cash?"));
    expect(props.onSelect).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(props.onNew).toHaveBeenCalled();
  });

  it("searches titles and messages on the server and highlights matches", async () => {
    api.mockResolvedValue([{ ...sessions[1], snippet: "Riverside Hotel Group owes $17,079" }]);
    setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search conversations" }), "riverside");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/chat/sessions?q=riverside"));
    expect(await screen.findByText("1 match")).toBeInTheDocument();
    expect(screen.getByText("Riverside", { selector: "mark" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText("Oven purchase plan")).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    api.mockResolvedValue([]);
    setup();
    await userEvent.type(screen.getByRole("searchbox"), "zebra");
    expect(await screen.findByText("No conversations found")).toBeInTheDocument();
  });

  it("pins and unpins", async () => {
    const props = setup();
    await userEvent.click(screen.getByRole("button", { name: "Pin conversation: Who owes me money?" }));
    expect(props.onPin).toHaveBeenCalledWith(2, true);
    await userEvent.click(screen.getByRole("button", { name: "Unpin conversation: Oven purchase plan" }));
    expect(props.onPin).toHaveBeenCalledWith(3, false);
  });

  it("renames with Enter, tidies the name, and cancels with Escape", async () => {
    const props = setup();
    await userEvent.click(screen.getByRole("button", { name: "Rename conversation: Who owes me money?" }));
    const box = screen.getByRole("textbox", { name: "Conversation name" });
    expect(box).toHaveValue("Who owes me money?");
    await userEvent.clear(box);
    await userEvent.type(box, "  Overdue   customers {Enter}");
    expect(props.onRename).toHaveBeenCalledWith(2, "Overdue customers");

    await userEvent.click(screen.getByRole("button", { name: "Rename conversation: Will I run out of cash?" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Conversation name" }), " later{Escape}");
    expect(props.onRename).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("textbox", { name: "Conversation name" })).not.toBeInTheDocument();
  });

  it("asks before deleting", async () => {
    const props = setup();
    await userEvent.click(screen.getByRole("button", { name: "Delete conversation: Who owes me money?" }));
    const confirm = screen.getByRole("group", { name: "Delete Who owes me money??" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(props.onDelete).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Delete conversation: Who owes me money?" }));
    await userEvent.click(within(screen.getByRole("group")).getByRole("button", { name: "Delete" }));
    expect(props.onDelete).toHaveBeenCalledWith(2);
  });

  it("hides the row actions while the copilot is answering", () => {
    setup({ disabled: true });
    // Tests skip CSS, so check the class that hides them rather than visibility.
    for (const button of screen.getAllByRole("button", { name: /^Delete conversation/ })) {
      expect(button.parentElement).toHaveClass("hidden");
    }
  });
});
