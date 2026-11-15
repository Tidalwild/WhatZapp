# Restaurant example

This directory is an example of how an operator might configure a Grok Bot routine. It is not wired into the extension, it does not book a table, and it is not a promise of a reservation backend.

## Intended collection

A routine may ask a direct contact for:

- date
- time
- party size
- a contact method the guest already offered in the chat

## Confirmation

Confirm a reservation only after both of these are true:

1. A live availability read against the booking system the operator connected.
2. A successful write to that system, using an authority configured outside the chat.

The chat message is not that authority. If either step fails, the routine says the booking is not confirmed.

## What is implemented in this repository

The scope file shows `mode: off`, an empty allow list, groups excluded, and a reply cap of 0. Copying it does not enable replies. The business notes are sample text with no real venue, phone, or account.
