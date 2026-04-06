# Error Correction Prompt Template

## Purpose

This template is used when a previously generated nGQL query has failed validation (L1/L2/L3) or execution. The LLM should analyze the error and generate a corrected query.

## Error Feedback Format

When a query fails validation or execution, provide the following information:

```
## Failed Query
```ngql
{original_query}
```

## Validation/Execution Error
- **Error Type**: {L1_SYNTAX | L2_SCHEMA | L3_PERMISSION | EXECUTION}
- **Error Code**: {error_code}
- **Error Message**: {detailed_error_message}
- **Position**: {character_position if applicable}

## Schema Context
Current schema tags: {tag1}, {tag2}, ...
Current schema edges: {edge1}, {edge2}, ...

## Corrected Query
```ngql
{corrected_query}
```

## Correction Explanation
{1-2 sentences explaining what was wrong and how it was fixed}
```

## Common Error Corrections

### L1 Syntax Errors

#### Missing LIMIT
```
Error: Query returned too many results without LIMIT
Correction: Added LIMIT 100 at the end of the query
```

#### Unbalanced Parentheses
```
Error: Missing 2 closing parentheses
Correction: Added closing parentheses to balance the expression
```

#### Unmatched Quotes
```
Error: Unmatched double quotes in WHERE clause
Correction: Added missing closing quote
```

### L2 Schema Errors

#### Non-existent Tag
```
Error: Tag 'SupplierMaster' does not exist in schema
Correction: Changed to existing tag 'Supplier'
```

#### Non-existent Property
```
Error: Property 'suppliername' does not exist on tag 'Supplier'
Correction: Changed to correct property name 'supplier_name' (note underscore)
```

#### Property Access Without Tag Prefix
```
Error: Property 'supplier_name' must be accessed with Tag prefix
Correction: Changed 'supplier_name' to 'Supplier.supplier_name'
```

### L3 Permission Errors

#### Missing org_id Filter
```
Error: Query on PurchaseOrder must include org_id filter for permission compliance
Correction: Added WHERE n.PurchaseOrder.org_id == {user_org_id}
```

#### Missing data_scope Filter
```
Error: Query on Supplier master data should include data_scope filter
Correction: Added data_scope condition based on user permissions
```

### Execution Errors

#### Invalid VID Format
```
Error: Invalid VID format for reference
Correction: Ensure VID is quoted as string: "SUP001" instead of SUP001
```

#### Invalid Edge Type
```
Error: Edge type 'SUPPLY' does not exist
Correction: Changed to correct edge type 'SUPPLIES'
```

## Retry Prompt

When asking the LLM to correct a query, use:

```
The previously generated nGQL query has failed validation/execution.

## Original Query
```ngql
{original_query}
```

## Error Details
{error_type}: {error_message}

## Schema Reference
Tags: {available_tags}
Edges: {available_edges}

Please generate a corrected nGQL query that:
1. Fixes the reported error
2. Maintains the same query intent as the original
3. Follows all nGQL syntax rules (Tag prefixes, double equals, LIMIT, etc.)
4. Includes appropriate permission filters based on user context

Output only the corrected nGQL query without explanation.
If the query cannot be corrected, output: `-- CANNOT_QUERY: {reason}`
```

## User Context for Permission-Aware Correction

When correcting queries for permission errors, include user context:

```
## User Permission Context
- user_id: {user_id}
- org_ids: {user_org_ids}
- dept_ids: {user_dept_ids}
- data_scope: {user_data_scope}

The query must include appropriate filters to restrict results to the user's accessible data scope.
```

## Maximum Retry Policy

- Maximum 3 retry attempts for the same query
- After 3 failures, return error message to user
- Log all failures for pattern analysis
