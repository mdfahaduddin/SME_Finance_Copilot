import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Mail } from "lucide-react";
import { describe, expect, it } from "vitest";
import { FormError, PasswordField, TextField } from "./Field";
import { StrengthMeter } from "./StrengthMeter";

describe("form fields", () => {
  it("labels inputs and shows an error instead of the hint", () => {
    const { rerender } = render(<TextField label="Email" icon={Mail} hint="We never share it" />);
    expect(screen.getByRole("textbox", { name: /^Email/ })).toBeInTheDocument();
    expect(screen.getByText("We never share it")).toBeInTheDocument();
    rerender(<TextField label="Email" icon={Mail} hint="We never share it" error="Enter a valid email" />);
    expect(screen.getByRole("textbox", { name: /^Email/ })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter a valid email")).toBeInTheDocument();
    expect(screen.queryByText("We never share it")).not.toBeInTheDocument();
  });

  it("lets the user show and hide a password", async () => {
    render(<PasswordField label="Password" labelAction={<a href="/forgot-password">Forgot password?</a>} />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input).toHaveAttribute("type", "password");
    expect(screen.getByRole("link", { name: "Forgot password?" })).toBeInTheDocument();
  });

  it("renders form errors as alerts, and nothing without one", () => {
    const { container, rerender } = render(<FormError message={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<FormError message="Passwords do not match" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Passwords do not match");
  });
});

describe("password strength meter", () => {
  it.each([
    ["", "At least 10 characters. A short sentence works well."],
    ["short", "5 more characters needed"],
    ["abcdefghij", "Okay"],
    ["Correct horse battery", "Very strong"],
  ])("%j -> %s", (password, label) => {
    render(<StrengthMeter password={password} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
