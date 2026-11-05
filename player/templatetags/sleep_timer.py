from django import template

from player.features.sleep_timer.options import timer_options

register = template.Library()


@register.simple_tag
def sleep_timer_options():
    return timer_options()
