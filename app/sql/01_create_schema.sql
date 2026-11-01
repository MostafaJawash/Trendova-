-- E-Commerce Database Schema
-- This script creates all seven tables for the E-Commerce application
-- Database: ecommerce
-- Engine: InnoDB
-- Character Set: utf8mb4

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------
-- Table: users
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the user',
  `name` VARCHAR(150) NOT NULL COMMENT 'User\'s full name',
  `email` VARCHAR(255) NOT NULL COMMENT 'User\'s email address (unique)',
  `password_hash` VARCHAR(255) NOT NULL COMMENT 'Hashed password (never store plaintext)',
  `role` VARCHAR(20) NOT NULL DEFAULT 'customer' COMMENT 'User role: admin or customer',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the user was created',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp when the user was last updated',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_users_email` (`email`),
  INDEX `idx_users_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: categories
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `categories` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the category',
  `name` VARCHAR(150) NOT NULL COMMENT 'Category name (unique)',
  `description` TEXT NULL COMMENT 'Category description',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the category was created',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp when the category was last updated',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_categories_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: products
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `products` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the product',
  `category_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to categories table',
  `name` VARCHAR(200) NOT NULL COMMENT 'Product name',
  `description` TEXT NULL COMMENT 'Product description',
  `price` DECIMAL(12,2) NOT NULL COMMENT 'Product price (non-negative)',
  `image_url` VARCHAR(500) NULL COMMENT 'URL to product image',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the product was created',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp when the product was last updated',
  PRIMARY KEY (`id`),
  INDEX `idx_category_id` (`category_id`),
  CONSTRAINT `ck_products_price` CHECK (price >= 0),
  CONSTRAINT `fk_products_category_id`
    FOREIGN KEY (`category_id`)
    REFERENCES `categories` (`id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: inventory
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `inventory` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the inventory record',
  `product_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to products table (unique - one-to-one)',
  `total_quantity` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total quantity in stock (non-negative)',
  `reserved_quantity` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Quantity reserved for orders (non-negative)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the inventory record was created',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp when the inventory record was last updated',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_inventory_product_id` (`product_id`),
  CONSTRAINT `ck_inventory_reserved_not_exceed_total` CHECK (reserved_quantity <= total_quantity),
  CONSTRAINT `fk_inventory_product_id`
    FOREIGN KEY (`product_id`)
    REFERENCES `products` (`id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: orders
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `orders` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the order',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to users table',
  `total_amount` DECIMAL(14,2) NOT NULL COMMENT 'Total order amount (non-negative)',
  `status` VARCHAR(30) NOT NULL DEFAULT 'Pending' COMMENT 'Order status',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the order was created',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp when the order was last updated',
  PRIMARY KEY (`id`),
  INDEX `idx_orders_user_id` (`user_id`),
  INDEX `idx_orders_status` (`status`),
  CONSTRAINT `ck_orders_total_amount` CHECK (total_amount >= 0),
  CONSTRAINT `fk_orders_user_id`
    FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: order_items
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `order_items` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the order item',
  `order_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to orders table',
  `product_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to products table',
  `quantity` INT UNSIGNED NOT NULL COMMENT 'Quantity of the product (must be > 0)',
  `unit_price` DECIMAL(12,2) NOT NULL COMMENT 'Unit price at time of purchase (historical)',
  `subtotal` DECIMAL(14,2) NOT NULL COMMENT 'Subtotal = quantity * unit_price',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_order_items_order_product` (`order_id`, `product_id`),
  INDEX `idx_order_items_product_id` (`product_id`),
  CONSTRAINT `ck_order_items_quantity` CHECK (quantity > 0),
  CONSTRAINT `ck_order_items_unit_price` CHECK (unit_price >= 0),
  CONSTRAINT `ck_order_items_subtotal` CHECK (subtotal >= 0),
  CONSTRAINT `fk_order_items_order_id`
    FOREIGN KEY (`order_id`)
    REFERENCES `orders` (`id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT `fk_order_items_product_id`
    FOREIGN KEY (`product_id`)
    REFERENCES `products` (`id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table: favorites
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `favorites` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Unique identifier for the favorite record',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to users table',
  `product_id` BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to products table',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the product was favorited',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_favorites_user_product` (`user_id`, `product_id`),
  INDEX `idx_favorites_product_id` (`product_id`),
  CONSTRAINT `fk_favorites_user_id`
    FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT `fk_favorites_product_id`
    FOREIGN KEY (`product_id`)
    REFERENCES `products` (`id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
