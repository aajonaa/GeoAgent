from ...tools import Tool, ToolDefinition, ToolOutput


def register(registry):
    # Reuse the existing corrected source algorithm, not an asset execution adapter.
    from legacy.ToolsAgent.ToolsFuns.Geoscience.geoscience_common import geo_magnitude_to_energy
    from legacy.ToolsAgent.ToolsFuns.source_contracts import definition as source_definition

    contract = source_definition("GeoMagnitudeToEnergy")
    definition = ToolDefinition("GeoMagnitudeToEnergy", "Estimate earthquake radiated energy and TNT equivalent from moment magnitude.",
        "An earthquake energy estimate is requested with a known Mw; not magnitude-intensity conversion.",
        contract["input_schema"], contract["output_schema"])

    def execute(args, context):
        context.check()
        return ToolOutput(geo_magnitude_to_energy(args))

    registry.register(Tool(definition, execute, pure=True))
