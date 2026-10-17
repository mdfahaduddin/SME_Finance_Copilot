import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";

const auth = vi.hoisted(() => ({ login: vi.fn(), verifyMfa: vi.fn() }));
vi.mock("../lib/auth", () => ({ useAuth: () => auth }));

const renderLogin = () => render(<MemoryRouter><Login /></MemoryRouter>);

async function signIn(email = "owner@lotusbakery.example", password = "Owner#2026") {
  await userEvent.type(screen.getByRole("textbox", { name: "Email" }), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("sign-in page", () => {
  beforeEach(() => {
    auth.login.mockReset();
    auth.verifyMfa.mockReset();
  });

  it("signs in with email and password", async () => {
    auth.login.mockResolvedValue(false); // no two-factor step
    renderLogin();
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    await signIn();
    expect(auth.login).toHaveBeenCalledWith("owner@lotusbakery.example", "Owner#2026");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the server's error", async () => {
    auth.login.mockRejectedValue(new Error("Incorrect email or password"));
    renderLogin();
    await signIn("owner@lotusbakery.example", "wrong-password");
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
  });

  it("asks for the two-factor code when the account has it", async () => {
    auth.login.mockResolvedValue(true);
    auth.verifyMfa.mockResolvedValue(undefined);
    renderLogin();
    await signIn();
    expect(await screen.findByRole("heading", { name: "Two-factor verification" })).toBeInTheDocument();
    const code = screen.getByRole("textbox", { name: "Authentication code" });
    const verify = screen.getByRole("button", { name: /Verify and sign in/ });
    await userEvent.type(code, "12a34");
    expect(code).toHaveValue("1234"); // digits only
    expect(verify).toBeDisabled();
    await userEvent.type(code, "56");
    await userEvent.click(verify);
    expect(auth.verifyMfa).toHaveBeenCalledWith("123456");
  });

  it("links to password recovery and registration", () => {
    renderLogin();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/forgot-password");
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/register");
  });
});
