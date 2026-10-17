import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api", () => ({ api }));

const renderSidebar = () => render(<MemoryRouter initialEntries={["/reports"]}><Sidebar /></MemoryRouter>);

describe("sidebar", () => {
  beforeEach(() => {
    api.mockReset();
    api.mockResolvedValue([{ id: 1 }, { id: 2 }]); // two approvals waiting
  });

  it("lists every page and marks the current one", async () => {
    renderSidebar();
    for (const label of ["Dashboard", "Copilot", "Cash Flow", "Financing", "Approvals", "Reports", "Data", "Team", "Audit Log", "Settings"]) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Reports/ })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByLabelText("2 pending")).toBeInTheDocument();
  });

  it("collapses to an icon rail and remembers it", async () => {
    renderSidebar();
    const aside = screen.getByRole("complementary");
    expect(aside).toHaveClass("w-60");
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(aside).toHaveClass("w-[72px]");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem("sidebar-collapsed")).toBe("1");
  });

  it("starts collapsed when that was the last choice, and Ctrl+B toggles it", async () => {
    localStorage.setItem("sidebar-collapsed", "1");
    renderSidebar();
    const aside = screen.getByRole("complementary");
    expect(aside).toHaveClass("w-[72px]");
    await userEvent.keyboard("{Control>}b{/Control}");
    expect(aside).toHaveClass("w-60");
    expect(localStorage.getItem("sidebar-collapsed")).toBe("0");
  });
});
