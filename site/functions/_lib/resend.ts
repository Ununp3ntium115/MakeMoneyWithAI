export async function sendMagicLink(email: string, link: string, env: { RESEND_API_KEY: string }): Promise<void> {
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: 'MakeMoneyWithAI <login@makemoneywithai.dev>', to: [email],
      subject: 'Your login link', html: `<p><a href="${link}">Sign in</a> (valid 15 minutes).</p>`,
    }),
  });
  if (!res.ok) throw new Error(`Resend -> ${res.status}`);
}
