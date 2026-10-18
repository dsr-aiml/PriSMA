"use client";
import { useId, useState, type InputHTMLAttributes } from "react";

export function PasswordField({ label = "Password", ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  const id = useId(), [visible, setVisible] = useState(false);
  return <label htmlFor={id} className="password-label">{label}<span className="password-control">
    <input {...props} id={id} type={visible ? "text" : "password"} />
    <button className={`password-visibility ${visible ? "is-visible" : ""}`} type="button" aria-label={visible ? "Hide " + label.toLowerCase() : "Show " + label.toLowerCase()} aria-pressed={visible} onMouseDown={event => event.preventDefault()} onClick={() => setVisible(value => !value)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path className="eye-outline" d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle className="eye-pupil" cx="12" cy="12" r="2.6" /><path className="eye-slash" d="m4 4 16 16" /></svg>
    </button>
  </span></label>;
}
