# Licence: MIT. Derived one-to-one from the pinned Northwind SQLite schema.
# ModelSpec 1.0-draft; OrderDetails represents the native SQLite table "Order Details" (ModelSpec published entity names must be identifiers).

entity "Categories" {
  key = ["CategoryID"]

  property "CategoryID" {
    required = true
    type = "int"
  }

  property "CategoryName" {
    type = "string"
  }

  property "Description" {
    type = "string"
  }

  property "Picture" {
    type = "document"
  }
}

entity "CustomerCustomerDemo" {
  key = ["CustomerID", "CustomerTypeID"]

  property "CustomerID" {
    required = true
    entity = "Customers"
  }

  property "CustomerTypeID" {
    required = true
    entity = "CustomerDemographics"
  }
}

entity "CustomerDemographics" {
  key = ["CustomerTypeID"]

  property "CustomerTypeID" {
    required = true
    type = "string"
  }

  property "CustomerDesc" {
    type = "string"
  }
}

entity "Customers" {
  key = ["CustomerID"]

  property "CustomerID" {
    required = true
    type = "string"
  }

  property "CompanyName" {
    type = "string"
  }

  property "ContactName" {
    type = "string"
  }

  property "ContactTitle" {
    type = "string"
  }

  property "Address" {
    type = "string"
  }

  property "City" {
    type = "string"
  }

  property "Region" {
    type = "string"
  }

  property "PostalCode" {
    type = "string"
  }

  property "Country" {
    type = "string"
  }

  property "Phone" {
    type = "string"
  }

  property "Fax" {
    type = "string"
  }
}

entity "EmployeeTerritories" {
  key = ["EmployeeID", "TerritoryID"]

  property "EmployeeID" {
    required = true
    entity = "Employees"
  }

  property "TerritoryID" {
    required = true
    entity = "Territories"
  }
}

entity "Employees" {
  key = ["EmployeeID"]

  property "EmployeeID" {
    required = true
    type = "int"
  }

  property "LastName" {
    type = "string"
  }

  property "FirstName" {
    type = "string"
  }

  property "Title" {
    type = "string"
  }

  property "TitleOfCourtesy" {
    type = "string"
  }

  property "BirthDate" {
    type = "date"
  }

  property "HireDate" {
    type = "date"
  }

  property "Address" {
    type = "string"
  }

  property "City" {
    type = "string"
  }

  property "Region" {
    type = "string"
  }

  property "PostalCode" {
    type = "string"
  }

  property "Country" {
    type = "string"
  }

  property "HomePhone" {
    type = "string"
  }

  property "Extension" {
    type = "string"
  }

  property "Photo" {
    type = "document"
  }

  property "Notes" {
    type = "string"
  }

  property "ReportsTo" {
    entity = "Employees"
  }

  property "PhotoPath" {
    type = "string"
  }
}

entity "OrderDetails" {
  key = ["OrderID", "ProductID"]

  property "OrderID" {
    required = true
    entity = "Orders"
  }

  property "ProductID" {
    required = true
    entity = "Products"
  }

  property "UnitPrice" {
    required = true
    type = "decimal"
  }

  property "Quantity" {
    required = true
    type = "int"
  }

  property "Discount" {
    required = true
    type = "decimal"
  }
}

entity "Orders" {
  key = ["OrderID"]

  property "OrderID" {
    required = true
    type = "int"
  }

  property "CustomerID" {
    entity = "Customers"
  }

  property "EmployeeID" {
    entity = "Employees"
  }

  property "OrderDate" {
    type = "datetime"
  }

  property "RequiredDate" {
    type = "datetime"
  }

  property "ShippedDate" {
    type = "datetime"
  }

  property "ShipVia" {
    entity = "Shippers"
  }

  property "Freight" {
    type = "decimal"
  }

  property "ShipName" {
    type = "string"
  }

  property "ShipAddress" {
    type = "string"
  }

  property "ShipCity" {
    type = "string"
  }

  property "ShipRegion" {
    type = "string"
  }

  property "ShipPostalCode" {
    type = "string"
  }

  property "ShipCountry" {
    type = "string"
  }
}

entity "Products" {
  key = ["ProductID"]

  property "ProductID" {
    required = true
    type = "int"
  }

  property "ProductName" {
    required = true
    type = "string"
  }

  property "SupplierID" {
    entity = "Suppliers"
  }

  property "CategoryID" {
    entity = "Categories"
  }

  property "QuantityPerUnit" {
    type = "string"
  }

  property "UnitPrice" {
    type = "decimal"
  }

  property "UnitsInStock" {
    type = "int"
  }

  property "UnitsOnOrder" {
    type = "int"
  }

  property "ReorderLevel" {
    type = "int"
  }

  property "Discontinued" {
    required = true
    type = "string"
  }
}

entity "Regions" {
  key = ["RegionID"]

  property "RegionID" {
    required = true
    type = "int"
  }

  property "RegionDescription" {
    required = true
    type = "string"
  }
}

entity "Shippers" {
  key = ["ShipperID"]

  property "ShipperID" {
    required = true
    type = "int"
  }

  property "CompanyName" {
    required = true
    type = "string"
  }

  property "Phone" {
    type = "string"
  }
}

entity "Suppliers" {
  key = ["SupplierID"]

  property "SupplierID" {
    required = true
    type = "int"
  }

  property "CompanyName" {
    required = true
    type = "string"
  }

  property "ContactName" {
    type = "string"
  }

  property "ContactTitle" {
    type = "string"
  }

  property "Address" {
    type = "string"
  }

  property "City" {
    type = "string"
  }

  property "Region" {
    type = "string"
  }

  property "PostalCode" {
    type = "string"
  }

  property "Country" {
    type = "string"
  }

  property "Phone" {
    type = "string"
  }

  property "Fax" {
    type = "string"
  }

  property "HomePage" {
    type = "string"
  }
}

entity "Territories" {
  key = ["TerritoryID"]

  property "TerritoryID" {
    required = true
    type = "string"
  }

  property "TerritoryDescription" {
    required = true
    type = "string"
  }

  property "RegionID" {
    required = true
    entity = "Regions"
  }
}
