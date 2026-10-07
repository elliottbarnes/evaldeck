export const fixtures = [
  {
    "id": "ticket-routing",
    "prompt": "Classify this synthetic support ticket: 'I was charged twice this month.' Return JSON with category (billing or technical) and confidence (0 to 1).",
    "checks": [
      {
        "type": "json"
      },
      {
        "type": "required_keys",
        "keys": [
          "category",
          "confidence"
        ]
      },
      {
        "type": "equals",
        "path": "/category",
        "value": "billing"
      },
      {
        "type": "number_range",
        "path": "/confidence",
        "min": 0.8,
        "max": 1
      }
    ],
    "baseline": "{\"category\":\"billing\",\"confidence\":0.94}",
    "candidate": "{\"category\":\"technical\",\"confidence\":0.91}"
  },
  {
    "id": "amount-extraction",
    "prompt": "Extract the refund amount from this synthetic note: 'Please refund the duplicate charge of $42.50.' Return JSON with numeric amount and currency USD.",
    "checks": [
      {
        "type": "required_keys",
        "keys": [
          "amount",
          "currency"
        ]
      },
      {
        "type": "equals",
        "path": "/currency",
        "value": "USD"
      },
      {
        "type": "number_range",
        "path": "/amount",
        "min": 42.5,
        "max": 42.5
      }
    ],
    "baseline": "{\"amount\":42.5,\"currency\":\"USD\"}",
    "candidate": "{\"amount\":\"42.50\",\"currency\":\"USD\"}"
  },
  {
    "id": "concise-answer",
    "prompt": "Return the exact phrase: Your request is being reviewed.",
    "checks": [
      {
        "type": "equals",
        "value": "Your request is being reviewed."
      },
      {
        "type": "contains",
        "value": "being reviewed"
      }
    ],
    "baseline": "Your request is being reviewed.",
    "candidate": "Your request is being reviewed."
  },
  {
    "id": "escalation-flag",
    "prompt": "A synthetic support ticket contains a duplicated payment, but no security concern. Return JSON with escalate false and owner null.",
    "checks": [
      {
        "type": "equals",
        "path": "/escalate",
        "value": false
      },
      {
        "type": "equals",
        "path": "/owner",
        "value": null
      }
    ],
    "baseline": "{\"escalate\":false,\"owner\":null}",
    "candidate": "{\"escalate\":false,\"owner\":null}"
  },
  {
    "id": "literal-markup",
    "prompt": "Echo this text literally, without executing it: <script>alert('synthetic')</script>",
    "checks": [
      {
        "type": "equals",
        "value": "<script>alert('synthetic')</script>"
      }
    ],
    "baseline": "<script>alert('synthetic')</script>",
    "candidate": "<script>alert('synthetic')</script>"
  }
];
