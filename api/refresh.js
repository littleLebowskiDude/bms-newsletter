// Called by the Vercel cron in vercel.json. Starts a fresh deployment, which re-runs
// tools/build.py and so picks up any newsletter the school has published since.
// Needs two environment variables in the Vercel project:
//   CRON_SECRET      any long random string (Vercel sends it with cron requests)
//   DEPLOY_HOOK_URL  a Deploy Hook for the main branch (Settings -> Git -> Deploy Hooks)
module.exports = async (req, res) => {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.authorization !== `Bearer ${secret}`) {
    return res.status(401).json({ error: 'unauthorised' });
  }
  const hook = process.env.DEPLOY_HOOK_URL;
  if (!hook) return res.status(500).json({ error: 'DEPLOY_HOOK_URL is not set' });
  const r = await fetch(hook, { method: 'POST' });
  return res.status(r.ok ? 200 : 502).json({ triggered: r.ok });
};
