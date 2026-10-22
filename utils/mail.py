from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_smtp_mail(subject, from_email, to, context, fall_back_default_text_context=" Welcome to our Bank App!"):
    # Sends an email with an HTML version (templates/messages.html) and a
    # plain text version for email apps that can't show HTML.
    #   subject:    the email subject
    #   from_email: who it's from
    #   to:         a list of email addresses
    #   context:    the values to put into the HTML template
    html_content = render_to_string("messages.html", context)
    text_content = fall_back_default_text_context

    email = EmailMultiAlternatives(subject, text_content, from_email, to)
    email.attach_alternative(html_content, "text/html")
    email.send()
