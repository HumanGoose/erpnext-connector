"""GraphQL Admin API mutation documents (per ADR-0001).

These back the semantic write methods on `ShopifyClient`. Sync-handler tests
run against `FakeShopifyClient` and never see these strings; they exist so the
real client is usable against a live store during manual e2e validation (issue
24). Field selections are deliberately small — just the identifiers the sync
handlers store back as Synced Entity references.
"""

PRODUCT_BY_HANDLE_QUERY = """
query ConnectorProductByHandle($handle: String!) {
  products(first: 1, query: $handle) {
    nodes {
      id
      handle
      variants(first: 100) { nodes { id sku inventoryItem { id } } }
    }
  }
}
"""

PRODUCT_CREATE = """
mutation ConnectorProductCreate($input: ProductInput!) {
  productCreate(input: $input) {
    product {
      id
      variants(first: 100) { nodes { id sku inventoryItem { id } } }
    }
    userErrors { field message }
  }
}
"""

PRODUCT_UPDATE = """
mutation ConnectorProductUpdate($input: ProductInput!) {
  productUpdate(input: $input) {
    product { id }
    userErrors { field message }
  }
}
"""

PRODUCT_VARIANTS_BULK_CREATE = """
mutation ConnectorVariantsCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    productVariants { id sku inventoryItem { id } }
    userErrors { field message }
  }
}
"""

PRODUCT_VARIANTS_BULK_UPDATE = """
mutation ConnectorVariantsUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id sku price }
    userErrors { field message }
  }
}
"""

PRODUCT_MEDIA_QUERY = """
query ConnectorProductMedia($id: ID!) {
  product(id: $id) {
    media(first: 250) {
      nodes { ... on MediaImage { image { url } } }
    }
  }
}
"""

PRODUCT_IMAGES_QUERY = """
query ConnectorProductImages($id: ID!) {
  product(id: $id) {
    images(first: 250) {
      nodes { id src }
    }
  }
}
"""

PRODUCT_CREATE_MEDIA = """
mutation ConnectorProductCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { ... on MediaImage { id } }
    mediaUserErrors { field message }
    userErrors: mediaUserErrors { field message }
  }
}
"""

INVENTORY_SET_QUANTITIES = """
mutation ConnectorInventorySet($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) {
    inventoryAdjustmentGroup { createdAt }
    userErrors { field message }
  }
}
"""

CUSTOMER_CREATE = """
mutation ConnectorCustomerCreate($input: CustomerInput!) {
  customerCreate(input: $input) {
    customer { id }
    userErrors { field message }
  }
}
"""

CUSTOMER_UPDATE = """
mutation ConnectorCustomerUpdate($input: CustomerInput!) {
  customerUpdate(input: $input) {
    customer { id }
    userErrors { field message }
  }
}
"""

# orderCreate is invoked with the @idempotent directive (per ADR-0001) via the
# request `extensions.idempotencyKey`, so retries can't create duplicate orders.
ORDER_CREATE = """
mutation ConnectorOrderCreate($order: OrderCreateOrderInput!) {
  orderCreate(order: $order) {
    order { id }
    userErrors { field message }
  }
}
"""

ORDER_CANCEL = """
mutation ConnectorOrderCancel($orderId: ID!, $reason: OrderCancelReason!, $refund: Boolean!, $restock: Boolean!, $notifyCustomer: Boolean) {
  orderCancel(orderId: $orderId, reason: $reason, refund: $refund, restock: $restock, notifyCustomer: $notifyCustomer) {
    job { id }
    orderCancelUserErrors { field message }
    userErrors: orderCancelUserErrors { field message }
  }
}
"""

FULFILLMENT_CREATE = """
mutation ConnectorFulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment { id status }
    userErrors { field message }
  }
}
"""

PRODUCT_DELETE = """
mutation ConnectorProductDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""

PRODUCT_VARIANTS_BULK_DELETE = """
mutation ConnectorVariantsDelete($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    product { id }
    userErrors { field message }
  }
}
"""
