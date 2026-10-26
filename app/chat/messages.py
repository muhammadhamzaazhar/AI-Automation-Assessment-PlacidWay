"""Fixed replies. They are written here, not generated, so they can never contain invented
facts. Non-English visitors get a cached machine translation."""

GREETING = (
    "Hello! I can answer questions about ITC Immunity Therapy Center in Tijuana, Mexico: its "
    "alternative cancer treatment packages, prices and services, and alternative medicine "
    "costs abroad. What would you like to know?"
)

OUT_OF_SCOPE = (
    "Sorry, I can only help with questions about the treatments, clinics and prices on "
    "PlacidWay's pages, such as ITC Immunity Therapy Center in Tijuana and its cancer "
    "treatment packages."
)

BOOKING = (
    "I can't book appointments or check availability. To arrange treatment, request a free "
    "quote from PlacidWay: their team will contact you about dates and next steps. Use the "
    "button below, or leave your name and email here."
)

QUOTE_REQUEST = (
    "Happy to help you get a free, no-obligation quote. Use the button below, or leave your "
    "name and email here and PlacidWay's team will contact you."
)

MEDICAL_ADVICE = (
    "I can't give medical advice or say whether a treatment is safe or suitable for your health "
    "situation. Please discuss this with your doctor. PlacidWay can also put you in touch with "
    "the clinic's medical team, who can review your medical history: request a free quote "
    "below to start."
)

NOT_FOUND = (
    "I couldn't find that information on the PlacidWay pages I have. For accurate details, "
    "please request a free quote and PlacidWay's team will get back to you."
)

UNAVAILABLE = (
    "Sorry, I'm having trouble answering right now. Please try again in a moment, or contact "
    "PlacidWay directly for a free quote."
)

DISCLAIMER = (
    "This is general information from PlacidWay's website, not medical advice. Please consult "
    "a qualified doctor about your own situation."
)

CANNED_REPLIES = {
    "greeting": GREETING,
    "out_of_scope": OUT_OF_SCOPE,
    "booking": BOOKING,
    "quote_request": QUOTE_REQUEST,
    "medical_advice": MEDICAL_ADVICE,
}
