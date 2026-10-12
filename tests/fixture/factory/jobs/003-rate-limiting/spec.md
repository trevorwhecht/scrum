# Rate limiting on login
UI surface: no
Hard stops: auth

## Acceptance criteria
1. 6th failed login within 60s returns 429 (verify: `rate-limit.test.ts`)

<script>alert("xss")</script>
