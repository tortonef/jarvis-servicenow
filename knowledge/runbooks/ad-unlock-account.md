---
id: RB-AD-001
title: Unlock a locked-out Active Directory account
audience: [service-desk, maintenance]
systems: [active-directory]
symptoms: ["account locked out", "user can't sign in", "LockedOut true"]
owner: identity-team
review_by: 2027-05-01
---

## When to use
A user is locked out of `helios.local` and the identity has been verified. Risk: low, affects one user.

## Pre-checks
1. Confirm the lockout: `Get-ADUser <sam> -Properties LockedOut,LastBadPasswordAttempt,BadLogonCount`.
2. Check the account is in `OU=Staff,DC=helios,DC=local`. Never unlock service or admin accounts with this runbook.

## Steps
1. `Unlock-ADAccount -Identity <sam>`.
2. Add a work note with the time and the `LastBadPasswordAttempt` value.

## Verify
`Get-ADUser <sam> -Properties LockedOut` returns `LockedOut : False`.

## If it locks again within an hour
Find the source with RB-AD-002.
