"""Customer-facing copy. Owned by the frontend team."""

TAGLINE = "Cloud tools for teams that ship."
BUY_LABEL = "Buy"

PLAN_DETAILS = {
    "Starter": {
        "blurb": "For side projects and small apps getting their first users.",
        "features": [
            "3 apps, 1 vCPU / 1 GB each",
            "Managed Postgres, 10 GB",
            "Global edge CDN",
            "Community support",
        ],
    },
    "Team": {
        "blurb": "For product teams shipping to production every day.",
        "features": [
            "Unlimited apps, autoscaling compute",
            "Managed Postgres, 100 GB + daily backups",
            "Preview environments for every pull request",
            "Logs, metrics and alerts",
            "Email support, 1 business day",
        ],
    },
    "Business": {
        "blurb": "For companies that need compliance, SSO and guarantees.",
        "features": [
            "Everything in Team",
            "Dedicated compute and private networking",
            "SSO, audit logs and role-based access",
            "99.99% uptime SLA",
            "24/7 support, 1-hour response",
        ],
    },
}
