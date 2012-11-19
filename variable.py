# coding=utf-8
"""Adds capacity for caching logic within template views as a variable"""
from contextlib import contextmanager
from django.conf import settings
from django.template import Node, Library, StringOrigin, Lexer, Parser
from django.utils.safestring import mark_safe
import re


register = Library()
# Tokenize a token using regex (as default token splitter doesn't do this
# properly. This will not validate the form of the token, however when
# utilized, there will be less tokens than expected if there are errors.
TOKEN_REGEX = re.compile(
    # Match and group token contents
    r'(\w+)=' # Match alphabetical or _ followed by = for name assignment
    r'(?:' # Non-grouped parenthesis
        r'(".*?")' # Non-greedy match-all (match up to look-aheads)
        r'(?<!\\")' # Negative look behind matching \" (not proceeded by \")*.
        r'|' # OR
        r'(\w+)' # Match alphabetical or _
    r')' # End non-grouped parenthesis
    # Match end of token
    r'(?:' # Non-grouped parenthesis
        r'(?= )' # Look ahead matching space (proceeded by space)
        r'|' # OR
        r'$' # Match against end of text
    r')' # End non-grouped parenthesis
)
# *: If you're using double backslashes here to escape a backslash, then
#    bad luck. A proper parser should work for this extreme edge case.


def get_token_groups(text):
    """Retrieve token groupings from text
    Will retrieve token groupings for use with variables. A token is
    defined as two elements:
        A variable name consisting of letters or an underscore
        A value that must be surrounded by double quotes
    :param text: A raw string containing the token groups to be extracted
    :type text: basestring
    :return: A list of the token groups as tuples
    :rtype: list
    """
    token_groups = []
    for  match in TOKEN_REGEX.findall(text):
        token_groups.append(
            (match[0], match[1].strip('"') if match[1] else match[2]))

    return token_groups


@register.tag('variable')
def do_variable(parser, token):
    """Caches template logic within a context variable
    :param parser: The template parser.
    :param token: The tag tokens.
    :return: A TemplateVariableNode instance
    """
    token_text = token.contents
    # Remove this command from the token contents
    variable_token_text = token_text[token_text.index(' ') + 1:]
    group_tokens = get_token_groups(variable_token_text)
    # Parse until endvariable.
    nodelist = parser.parse(('endvariable',))

    # Delete ending tag from parse tree
    parser.delete_first_token()
    return TemplateVariableNode(nodelist, parser, group_tokens)


class LazyVariable(object):
    """A variable object that lazy evaluates its logic as a variable
    Note: Due to parsing problems {% %} need to be replaced with {[ ]}
    """
    def __init__(self, logic, tag_library, context):
        self._tag_library = tag_library
        self._logic = self._replace_django_tags(logic)
        self._context = context

    def _replace_django_tags(self, logic):
        return logic.replace('{[', '{%').replace(']}', '%}')

    def _resolve_value(self, context):
        if settings.TEMPLATE_DEBUG:
            from django.template.debug import DebugLexer, DebugParser
            lexer_class, parser_class = DebugLexer, DebugParser
        else:
            lexer_class, parser_class = Lexer, Parser

        lexer = lexer_class(self._logic, StringOrigin(self._logic))
        parser = parser_class(lexer.tokenize())
        parser.tags = self._tag_library
        nodelist = parser.parse()
        return u''.join(node.render(context) for node in nodelist)


    def resolve(self, context):
        try:
            value = self._cached_value
        except AttributeError:
            value = self._cached_value = self._resolve_value(context)

        return mark_safe(value)

    def __str__(self):
        return self.resolve(self._context)


class TemplateVariableNode(Node):
    """A template node for caching logic as a variable"""
    def __init__(self, nodelist, parser, variable_group_tokens):
        """Initializer for TemplateVariableNode
        :param nodelist: The nodelist underneath this node
        :type nodelist: NodeList
        :param parser: The template parser
        :type parser: Parser
        :param variable_group_tokens: Group tokens consisting of name and value
        :type variable_group_tokens: list
        """
        self._nodelist = nodelist
        self._parser = parser
        self._variable_group_tokens = variable_group_tokens

    @property
    def nodelist(self):
        """Returns the list of children nodes."""
        return self._nodelist

    def render(self, context):
        """Renders this node.
        Renders the context, inserting the custom scope of this instance
        when rendering the children nodes.
        :param context: The base context which will be extended.
        :return: A string containing the output of the rendering process.
        """
        with self.managed_custom_context(context) as new_context:
            return u''.join(node.render(new_context) for node in self.nodelist)

    @contextmanager
    def managed_custom_context(self, context):
        """Manages the context this node adds.
        A context manager that will handle the modification of the
        RequestContext instance passed. More efficient that copying a
        (possibly) large RequestContext instance.
        :param context: The context to modify.
        :return: A context manager instance that will yield the new context
            manager on entering and remove itself upon exiting.
        """
        variables_context = {}
        for variable_name, variable_logic in self._variable_group_tokens:
            variables_context[variable_name] = \
                LazyVariable(variable_logic, self._parser.tags, context)

        custom_context_dict = context.push()
        try:
            custom_context_dict.update(variables_context)
            yield context
        finally:
            context.pop()
