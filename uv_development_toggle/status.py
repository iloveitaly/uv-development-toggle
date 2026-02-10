import click


def format_status_label(label: str, color: str) -> str:
    return click.style(label, fg=color, bold=True)


def display_status(status_type, module_name, details=None):
    if details is None:
        details = {}
    """
    Display a formatted status message using rich console.

    Args:
        status_type: Type of status ('source_path', 'source_git', 'source_other', 'pypi', 'pypi_already',
                                    'error', 'warning', 'info', 'found_editable')
        module_name: Name of the module being processed
        details: Additional details or data to display (e.g., source configuration)
    """
    if status_type == "source_path":
        message = f"Set {module_name} source to local path: {details['path']}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "source_git":
        rev_info = f" (branch: {details.get('rev')})" if details.get("rev") else ""
        message = f"Set {module_name} source to Git repo: {details['git']}{rev_info}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "source_other":
        message = f"Set {module_name} source to: {details}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "pypi":
        message = f"Removing custom source for {module_name} to use PyPI version"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "pypi_already":
        message = f"Already using PyPI version for {module_name}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "error":
        message = f"Error: {details} for {module_name}"
        click.echo(f"{format_status_label('ERROR', 'red')} {message}")
    elif status_type == "warning":
        message = f"Warning: {details} for {module_name}"
        click.echo(f"{format_status_label('WARN', 'yellow')} {message}")
    elif status_type == "info":
        message = f"{details} for {module_name}"
        click.echo(f"{format_status_label('INFO', 'blue')} {message}")
    elif status_type == "found_editable":
        message = f"Found editable package {module_name}: {details.get('path')}"
        click.echo(f"{format_status_label('WARN', 'yellow')} {message}")
