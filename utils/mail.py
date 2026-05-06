from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives


def send_smtp_mail(subject, from_email, to, context, fall_back_default_text_context=" Welcome to our Bank App!"):
    """
    This function sends an email in both text and plain html content.

    Parameters:
    subject: the subject of the email
    from email: the sender's email address
    to: List of recipient email addresses 
    context: Dictionary of data to render in the html template
    """

    # Render HTML template with the given context
    html_content = render_to_string("messages.html", context)

    # Fallback plain text content for email  clients that dont support html
    text_content = fall_back_default_text_context

    # Create an email object with subjects, text content, sender and recipients
    msg = EmailMultiAlternatives(subject, text_content, from_email, to)

    # Attach the HTML version of the message 
    msg.attach_alternative(html_content, "text/html")

    # Send the email
    msg.send()