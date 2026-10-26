# Synthetic source fixtures

All examples are explicitly synthetic analytic data, not real geological or SAR observations. The closed array interface is fully hashed, including units and CRS/affine/mask/nodata. No file or weather data is downloaded.

numeric-oracles.json contains independent positive numeric expectations. negative-cases.json is a future-test specification, not an executed suite. Flow/LoG/MAD tolerances are proposed, not fitted to observed execution. No scientific dependency was imported or run during authoring.

Real use requires already processed and co-registered SAR products with real acquisition metadata; a declaration does not authenticate a sensor product.
