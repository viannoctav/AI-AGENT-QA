# PRD — E-Commerce Checkout & Payment

## 1. Document Information

**Product:** E-Commerce Web Application  
**Module:** Checkout & Payment  
**Document Purpose:** Complex QA test-case generation, coverage planning, traceability, and gap-analysis validation for AI-QA-Engineer V3.

---

## 2. Actors

- Customer
- Payment Gateway
- OTP Service
- Inventory Service

---

## 3. Feature Overview

Customer can review cart items, enter shipping information, select shipping method, optionally apply a coupon, choose a payment method, complete payment verification when required, and create an order.

The checkout process must prevent invalid input, stock over-allocation, duplicate order creation, invalid payment transitions, and repeated payment attempts beyond the configured business limit.

---

## 4. Functional Requirements

### FR-001 — Recipient Name

Customer must enter a recipient name.

Rules:
- Required.
- Length must be between 2 and 50 characters.
- Letters, spaces, apostrophes, and hyphens are allowed.

### FR-002 — Recipient Email

Customer must enter an email address for order confirmation.

Rules:
- Required.
- Must use a valid email format.
- Maximum length is 100 characters.

### FR-003 — Recipient Phone Number

Customer must enter a phone number.

Rules:
- Required.
- Must contain digits only.
- Length must be between 10 and 13 digits.
- Alphabetic characters are not allowed.
- Decimal values are not allowed.
- Special characters are not allowed.

### FR-004 — Shipping Address

Customer must enter a shipping address.

Rules:
- Required.
- Length must be between 10 and 200 characters.

### FR-005 — Postal Code

Customer must enter a postal code.

Rules:
- Required.
- Exactly 5 digits.
- Alphabetic characters are not allowed.
- Special characters are not allowed.

### FR-006 — Shipping Method

Customer must select one shipping method:
- Standard
- Express

Shipping fee rules:
- Standard shipping is free when cart subtotal is at least Rp500,000.
- Standard shipping is charged when cart subtotal is below Rp500,000.
- Express shipping is always chargeable.
- Only one shipping method can be selected.

### FR-007 — Coupon Code

Customer may enter a coupon code.

Rules:
- Coupon is optional.
- Only one coupon may be applied to an order.
- Coupon must be active.
- Expired coupon must be rejected.
- Coupon cannot be combined with another coupon.
- Minimum eligible cart subtotal is Rp100,000.
- Discount is 10% of eligible subtotal, capped at Rp50,000.

### FR-008 — Cart Item Quantity

Customer can change item quantity from checkout.

Rules:
- Minimum quantity is 1.
- Maximum quantity is 99 per item.
- Quantity cannot exceed currently available stock.
- Non-numeric quantity is invalid.
- Decimal quantity is invalid.

### FR-009 — Stock Validation

Before order creation, system must validate available stock.

Rules:
- Requested quantity must not exceed available stock.
- Insufficient stock must prevent order creation.
- Stock validation must happen before final order creation.

### FR-010 — Payment Method

Customer must select one payment method:
- Bank Transfer
- Card
- E-Wallet

Only one payment method can be active for one checkout transaction.

### FR-011 — Payment Processing

For Card and E-Wallet:
- Payment Gateway returns one of: SUCCESS, PENDING, FAILED.
- SUCCESS moves the order toward paid state.
- PENDING keeps the order waiting for payment confirmation.
- FAILED does not mark the order as paid.

For Bank Transfer:
- Order is created in pending-payment state while awaiting payment confirmation.

### FR-012 — Additional Verification

For payment totals above Rp1,000,000, the customer must complete OTP verification.

Rules:
- OTP contains exactly 6 digits.
- OTP expires after 5 minutes.
- Maximum incorrect OTP attempts is 3.
- Correct OTP within the validity period allows payment processing to continue.
- Expired or invalid OTP must not authorize payment.

### FR-013 — Payment Retry

Failed payment may be retried.

Rules:
- Customer may retry a failed payment up to 3 attempts.
- After the third failed payment attempt, the payment state becomes FAILED_FINAL.
- FAILED_FINAL payment cannot be retried again for the same transaction.

### FR-014 — Duplicate Checkout Submission

System must prevent duplicate order creation when customer submits the same checkout request multiple times.

Rules:
- Repeated submission of the same checkout transaction within 30 seconds must create only one order.
- Customer must not receive multiple order IDs for the same transaction.

### FR-015 — Order State Transition

Supported order states:

`DRAFT → PENDING_PAYMENT → PAID → PROCESSING → SHIPPED → COMPLETED`

Cancellation:
- DRAFT may be cancelled.
- PENDING_PAYMENT may be cancelled.
- PAID cannot be cancelled through the checkout screen.

Payment failure:
- PENDING_PAYMENT → PAYMENT_FAILED
- PAYMENT_FAILED → PENDING_PAYMENT when retry is still allowed
- PAYMENT_FAILED → FAILED_FINAL after the retry limit is reached

Expired payment:
- PENDING_PAYMENT → EXPIRED when the payment window expires.

### FR-016 — Payment Confirmation

When Payment Gateway confirms SUCCESS:
- Payment status becomes PAID.
- Order moves to PAID.
- The system stores the successful transaction reference.

When Payment Gateway returns FAILED:
- Payment status remains unpaid.
- Order must not move to PAID.

### FR-017 — Inventory Reservation

For an order waiting for payment:
- Requested stock is reserved while the order is pending payment.
- Reserved stock is released when the order becomes EXPIRED, CANCELLED, or FAILED_FINAL.

### FR-018 — Dependency Failure Handling

Checkout must handle dependency failures.

If Payment Gateway, OTP Service, or Inventory Service is unavailable or times out:
- Checkout must not create an incorrectly paid order.
- Customer receives an appropriate failure or retry message.
- The order state must remain consistent.

---

## 5. Non-Functional Requirements

### NFR-001 — Checkout Performance

For normal supported traffic, at least 95% of checkout requests must complete within 3 seconds, excluding time spent waiting for external payment confirmation.

### NFR-002 — Sensitive Data Protection

Sensitive payment information must not be written into application logs.

### NFR-003 — Idempotency

Repeated identical checkout requests within the configured 30-second protection window must produce one logical order.

### FR-004 — Account Lockout Enforcement on Login Failures

**Category:** Functional Requirement - Security Behavior

System must enforce account lockout on repeated primary authentication failures.

### NFR-005 — OTP Security

OTP must:
- be exactly 6 digits,
- expire after 5 minutes,
- stop accepting incorrect attempts after 3 failures.

---

## 6. Business Rules

| ID | Business Rule |
|---|---|
| BR-001 | Recipient phone number must contain 10–13 digits only. |
| BR-002 | Postal code must contain exactly 5 digits. |
| BR-003 | Recipient name length must be 2–50 characters. |
| BR-004 | Shipping address length must be 10–200 characters. |
| BR-005 | Email maximum length is 100 characters and must follow valid email format. |
| BR-006 | Standard shipping is free at subtotal >= Rp500,000. |
| BR-007 | Only one coupon can be applied to an order. |
| BR-008 | Coupon requires minimum subtotal Rp100,000. |
| BR-009 | Coupon discount is 10% and capped at Rp50,000. |
| BR-010 | Item quantity must be 1–99 and must not exceed available stock. |
| BR-011 | OTP is required for payment totals above Rp1,000,000. |
| BR-012 | OTP is valid for 5 minutes. |
| BR-013 | OTP accepts a maximum of 3 incorrect attempts. |
| BR-014 | Failed payment can be retried up to 3 times. |
| BR-015 | Duplicate checkout submission within 30 seconds creates one order. |
| BR-016 | Pending payment reserves inventory until the payment flow reaches a terminal state. |

---

## 7. Key State Model

### Order

`DRAFT`

→ `PENDING_PAYMENT`

→ `PAID`

→ `PROCESSING`

→ `SHIPPED`

→ `COMPLETED`

Alternative transitions:

`DRAFT → CANCELLED`

`PENDING_PAYMENT → CANCELLED`

`PENDING_PAYMENT → PAYMENT_FAILED`

`PAYMENT_FAILED → PENDING_PAYMENT`

`PAYMENT_FAILED → FAILED_FINAL`

`PENDING_PAYMENT → EXPIRED`

### Payment

`NOT_STARTED`

→ `PENDING`

→ `SUCCESS`

or

`PENDING → FAILED`

or

`FAILED → PENDING` when retry is still allowed

or

`FAILED → FAILED_FINAL` after retry limit.

---

## 8. Decision Table Targets

The following combinations are relevant for testing:

### Shipping Fee

Conditions:
- Shipping = Standard / Express
- Subtotal below / at-or-above free-shipping threshold

Expected behavior must reflect the shipping fee rule.

### Coupon Eligibility

Conditions:
- Coupon present / absent
- Coupon active / expired
- Subtotal below / at-or-above minimum
- Existing coupon already applied / not applied

Expected behavior must reflect the coupon rules.

### Payment Outcome

Conditions:
- Payment method
- Gateway result
- OTP requirement
- OTP result
- Retry count

Expected outcome must keep payment and order states consistent.

---

## 9. Edge-Case Areas

Relevant edge cases include:
- Leading or trailing whitespace.
- Minimum and maximum field lengths.
- Exactly-at-boundary values.
- One value below and above boundaries.
- Duplicate checkout submission.
- Repeated payment action.
- Payment timeout.
- OTP timeout.
- OTP incorrect attempt limit.
- Inventory changes between cart review and order creation.
- External dependency unavailable.
- Stale checkout state.
- Attempting an invalid state transition.

---

## 10. Expected QA Coverage

The requirement set is intentionally designed to produce coverage across:

- Positive Testing
- Negative Testing
- Equivalence Partitioning
- Boundary Value Analysis
- Decision Table
- State Transition
- Edge Case Testing
- Integration / Dependency Failure
- Security / Sensitive Data
- Performance-related NFR coverage

The AI must determine the exact number of test cases from the requirement complexity rather than using a fixed category count.

---

## 11. Test Data Guidance

Generated test data should be synthetic and safe for QA use.

Examples may include:
- Recipient Name: `Vita Anggun`
- Email: `vita@example.test`
- Phone: a synthetic numeric value satisfying the relevant length rule
- Postal Code: a synthetic 5-digit value
- Address: a synthetic address satisfying the specified length rule
- Coupon Code: a synthetic valid/invalid example when the requirement defines the condition
- OTP: a synthetic 6-digit value

For boundary tests, the generator must produce values that actually satisfy the required boundary condition.

---

## 12. Acceptance Criteria

The checkout module is acceptable when:

1. Valid customer data allows checkout to proceed.
2. Invalid field formats are rejected.
3. Required fields cannot be submitted empty.
4. Boundary constraints are enforced.
5. Coupon eligibility is evaluated correctly.
6. Stock quantity cannot exceed available stock.
7. Payment state matches Payment Gateway outcome.
8. OTP rules are enforced when required.
9. Payment retry limit is enforced.
10. Duplicate checkout requests do not create duplicate orders.
11. Invalid order-state transitions are rejected.
12. Dependency failures do not create inconsistent order/payment states.
13. Sensitive payment data is not written to logs.
14. Performance requirement is measurable under the stated condition.
